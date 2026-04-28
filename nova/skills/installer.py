"""Install skills from ClawHub into the local runtime skills directory."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import httpx

from nova.skills.models import SkillInstallResult
from nova.skills.scanner import SKILL_FILE_NAME, load_skill_document

DEFAULT_CLAWHUB_DOWNLOAD_BASE_URL = "https://wry-manatee-359.convex.site"


class SkillInstallError(RuntimeError):
    """Raised when a remote skill package cannot be installed safely."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "install_failed",
        next_action: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.next_action = next_action
        self.retry_after_seconds = retry_after_seconds


def _parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        seconds = int(text)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def normalize_clawhub_skill_slug(value: str) -> str:
    raw_value = value.strip()
    if not raw_value:
        raise SkillInstallError(
            "Usage: /install-skill <slug-or-url> [--force]",
            code="missing_skill_ref",
            next_action="provide_skill_ref",
        )

    parsed = urlparse(raw_value)
    if parsed.scheme and parsed.netloc:
        candidate = parsed.path.rstrip("/").split("/")[-1]
    else:
        candidate = raw_value.rstrip("/").split("/")[-1]

    slug = candidate.strip()
    if not slug:
        raise SkillInstallError(
            "Could not resolve a ClawHub skill slug from the provided input.",
            code="invalid_skill_ref",
            next_action="provide_valid_slug_or_url",
        )
    if any(part in {"", ".", ".."} for part in Path(slug).parts):
        raise SkillInstallError(
            f"Invalid ClawHub skill slug: {value}",
            code="invalid_skill_ref",
            next_action="provide_valid_slug_or_url",
        )
    return slug


def _resolve_base_url(base_url: str | None) -> str:
    resolved = (base_url or DEFAULT_CLAWHUB_DOWNLOAD_BASE_URL).strip().rstrip("/")
    return resolved or DEFAULT_CLAWHUB_DOWNLOAD_BASE_URL


def _validate_archive_member(name: str) -> PurePosixPath | None:
    if not name:
        return None
    relative = PurePosixPath(name)
    if relative.is_absolute():
        raise SkillInstallError(
            f"Unsafe archive path: {name}",
            code="unsafe_archive_path",
        )
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise SkillInstallError(
            f"Unsafe archive path: {name}",
            code="unsafe_archive_path",
        )
    return relative


def _extract_archive(content: bytes, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise SkillInstallError(
            "ClawHub returned an invalid skill archive.",
            code="invalid_archive",
        ) from exc

    with archive:
        for member in archive.infolist():
            relative = _validate_archive_member(member.filename)
            if relative is None:
                continue

            target = destination / Path(*relative.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)

            file_mode = member.external_attr >> 16
            if file_mode:
                try:
                    target.chmod(file_mode)
                except OSError:
                    pass


def _find_skill_root(extracted_root: Path) -> Path:
    root_skill_md = extracted_root / SKILL_FILE_NAME
    if root_skill_md.is_file():
        return extracted_root

    candidates = sorted(
        {
            skill_md.parent
            for skill_md in extracted_root.rglob(SKILL_FILE_NAME)
            if skill_md.is_file()
        },
        key=lambda path: str(path).lower(),
    )
    if len(candidates) != 1:
        raise SkillInstallError(
            "ClawHub archive must contain exactly one SKILL.md entrypoint.",
            code="invalid_archive_layout",
        )
    return candidates[0]


async def _download_skill_archive(*, slug: str, base_url: str) -> bytes:
    download_url = f"{base_url}/api/v1/download"
    headers = {"User-Agent": "nova"}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(download_url, params={"slug": slug}, headers=headers)
            response.raise_for_status()
            return response.content
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        if exc.response is not None and exc.response.status_code == 429:
            retry_after_seconds = _parse_retry_after(
                exc.response.headers.get("Retry-After"))
            raise SkillInstallError(
                f"ClawHub rate limited the download request for '{slug}' with HTTP 429.",
                code="rate_limited",
                next_action="retry_later",
                retry_after_seconds=retry_after_seconds,
            ) from exc
        if exc.response is not None and exc.response.status_code == 404:
            raise SkillInstallError(
                f"ClawHub could not find a skill named '{slug}'.",
                code="skill_not_found",
                next_action="check_slug_or_choose_another_skill",
            ) from exc
        raise SkillInstallError(
            f"ClawHub download failed for '{slug}' with HTTP {status_code}.",
            code="download_failed",
        ) from exc
    except httpx.HTTPError as exc:
        raise SkillInstallError(
            f"Failed to download skill '{slug}' from ClawHub: {exc}",
            code="download_failed",
        ) from exc


async def install_skill_from_clawhub(
    skill_ref: str,
    *,
    skills_dir: Path,
    force: bool = False,
    base_url: str | None = None,
) -> SkillInstallResult:
    slug = normalize_clawhub_skill_slug(skill_ref)
    resolved_base_url = _resolve_base_url(base_url)
    download_url = f"{resolved_base_url}/api/v1/download?slug={slug}"
    target_dir = skills_dir.expanduser().resolve() / slug

    if target_dir.exists() and not force:
        raise SkillInstallError(
            f"Skill '{slug}' already exists at {target_dir}. Re-run with --force to replace it.",
            code="already_exists",
            next_action="load_skill_or_force_install",
        )

    skills_dir.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    archive_bytes = await _download_skill_archive(slug=slug, base_url=resolved_base_url)

    with tempfile.TemporaryDirectory(
        prefix=f".nova-skill-{slug}-",
        dir=str(target_dir.parent),
    ) as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        extracted_root = temp_dir / "archive"
        extracted_root.mkdir(parents=True, exist_ok=True)
        _extract_archive(archive_bytes, extracted_root)

        source_root = _find_skill_root(extracted_root)
        staged_root = temp_dir / slug
        shutil.copytree(source_root, staged_root)

        document = load_skill_document(
            staged_root / SKILL_FILE_NAME, skills_dir=temp_dir)
        replaced = False
        if target_dir.exists():
            if not target_dir.is_dir():
                raise SkillInstallError(
                    f"Existing skill path is not a directory: {target_dir}",
                    code="invalid_target_path",
                )
            shutil.rmtree(target_dir)
            replaced = True

        staged_root.replace(target_dir)
        return SkillInstallResult(
            slug=slug,
            skill_name=document.name,
            installed_path=str(target_dir),
            skill_md_path=str(target_dir / SKILL_FILE_NAME),
            source_url=download_url,
            replaced=replaced,
        )
