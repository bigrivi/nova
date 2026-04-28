from __future__ import annotations

from io import BytesIO
import importlib
import json
from pathlib import Path
import zipfile

import httpx
import pytest

from nova.skills.service import SkillService
from nova.skills.installer import SkillInstallError, install_skill_from_clawhub
from nova.skills.tools import install_skill


def _build_skill_archive(*, root_dir: str = "review-skill", body: str = "Focus on correctness.\n") -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        prefix = f"{root_dir}/" if root_dir else ""
        archive.writestr(
            f"{prefix}SKILL.md",
            "---\n"
            "name: review-skill\n"
            "description: Review code changes.\n"
            "---\n\n"
            "# Review Skill\n\n"
            f"{body}",
        )
        archive.writestr(f"{prefix}references/checklist.md", "Check for regressions.\n")
    return buffer.getvalue()


class MockResponse:
    def __init__(self, *, content: bytes, status_code: int = 200, url: str, headers: dict | None = None):
        self.content = content
        self.status_code = status_code
        self.request = httpx.Request("GET", url)
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request, headers=self.headers),
            )


class MockAsyncClient:
    calls: list[dict] = []
    response_content: bytes = b""
    status_code: int = 200
    headers: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        MockAsyncClient.calls.append({"url": url, "params": params, "headers": headers})
        return MockResponse(
            content=MockAsyncClient.response_content,
            status_code=MockAsyncClient.status_code,
            url=f"{url}?slug={params['slug']}",
            headers=MockAsyncClient.headers,
        )


@pytest.mark.asyncio
async def test_install_skill_from_clawhub_downloads_and_extracts_archive(monkeypatch, tmp_path):
    installer_module = importlib.import_module("nova.skills.installer")
    MockAsyncClient.calls = []
    MockAsyncClient.response_content = _build_skill_archive()
    MockAsyncClient.status_code = 200
    MockAsyncClient.headers = {}
    monkeypatch.setattr(installer_module.httpx, "AsyncClient", MockAsyncClient)

    skills_dir = tmp_path / "skills"
    result = await install_skill_from_clawhub(
        "https://clawhub.ai/skills/team/review-skill",
        skills_dir=skills_dir,
    )

    installed_dir = skills_dir / "review-skill"
    assert result.slug == "review-skill"
    assert result.skill_name == "review-skill"
    assert result.replaced is False
    assert result.installed_path == str(installed_dir)
    assert result.source_url.endswith("/api/v1/download?slug=review-skill")
    assert (installed_dir / "SKILL.md").is_file()
    assert (installed_dir / "references" / "checklist.md").read_text(encoding="utf-8") == "Check for regressions.\n"
    assert MockAsyncClient.calls == [
        {
            "url": "https://wry-manatee-359.convex.site/api/v1/download",
            "params": {"slug": "review-skill"},
            "headers": {"User-Agent": "nova"},
        }
    ]


@pytest.mark.asyncio
async def test_install_skill_from_clawhub_rejects_existing_directory_without_force(tmp_path):
    skills_dir = tmp_path / "skills"
    existing_dir = skills_dir / "review-skill"
    existing_dir.mkdir(parents=True)
    (existing_dir / "SKILL.md").write_text("---\nname: review-skill\n---\n", encoding="utf-8")

    with pytest.raises(SkillInstallError, match="already exists"):
        await install_skill_from_clawhub("review-skill", skills_dir=skills_dir)


@pytest.mark.asyncio
async def test_install_skill_from_clawhub_force_replaces_existing_directory(monkeypatch, tmp_path):
    installer_module = importlib.import_module("nova.skills.installer")
    MockAsyncClient.calls = []
    MockAsyncClient.response_content = _build_skill_archive(body="Use the latest checklist.\n")
    MockAsyncClient.status_code = 200
    MockAsyncClient.headers = {}
    monkeypatch.setattr(installer_module.httpx, "AsyncClient", MockAsyncClient)

    skills_dir = tmp_path / "skills"
    existing_dir = skills_dir / "review-skill"
    existing_dir.mkdir(parents=True)
    (existing_dir / "SKILL.md").write_text(
        "---\nname: review-skill\n---\n\nOld content.\n",
        encoding="utf-8",
    )
    (existing_dir / "old.txt").write_text("legacy\n", encoding="utf-8")

    result = await install_skill_from_clawhub("review-skill", skills_dir=skills_dir, force=True)

    assert result.replaced is True
    assert (existing_dir / "SKILL.md").read_text(encoding="utf-8").endswith("Use the latest checklist.\n")
    assert not (existing_dir / "old.txt").exists()


@pytest.mark.asyncio
async def test_install_skill_tool_installs_skill_and_refreshes_catalog(monkeypatch, tmp_path):
    installer_module = importlib.import_module("nova.skills.installer")
    MockAsyncClient.calls = []
    MockAsyncClient.response_content = _build_skill_archive()
    MockAsyncClient.status_code = 200
    monkeypatch.setattr(installer_module.httpx, "AsyncClient", MockAsyncClient)

    service = SkillService(tmp_path / "skills")
    service.scan_skills()
    monkeypatch.setattr("nova.skills.tools.get_skill_service", lambda: service)

    result = await install_skill("review-skill")

    assert result.success is True
    payload = json.loads(result.content)
    assert payload["status"] == "ok"
    assert payload["action"] == "installed"
    assert payload["skill_name"] == "review-skill"
    assert payload["slug"] == "review-skill"
    assert payload["catalog_refreshed"] is True
    assert payload["skill_md_content_included"] is False
    assert "# Review Skill" not in result.content
    assert [skill.name for skill in service.list_skills()] == ["review-skill"]


@pytest.mark.asyncio
async def test_install_skill_tool_returns_failure_message(monkeypatch):
    class _FakeService:
        async def install_from_clawhub(self, skill_ref: str, *, force: bool = False):
            raise SkillInstallError(
                f"Cannot install {skill_ref}",
                code="download_failed",
                next_action="retry_later",
            )

    monkeypatch.setattr("nova.skills.tools.get_skill_service", lambda: _FakeService())

    result = await install_skill("review-skill")

    assert result.success is False
    assert result.error == "Cannot install review-skill"
    payload = json.loads(result.content)
    assert payload == {
        "status": "error",
        "error_code": "download_failed",
        "message": "Cannot install review-skill",
        "skill_ref": "review-skill",
        "force": False,
        "skill_md_content_included": False,
        "next_action": "retry_later",
    }


@pytest.mark.asyncio
async def test_install_skill_tool_returns_rate_limit_metadata(monkeypatch, tmp_path):
    installer_module = importlib.import_module("nova.skills.installer")
    MockAsyncClient.calls = []
    MockAsyncClient.response_content = b""
    MockAsyncClient.status_code = 429
    MockAsyncClient.headers = {"Retry-After": "60"}
    monkeypatch.setattr(installer_module.httpx, "AsyncClient", MockAsyncClient)

    service = SkillService(tmp_path / "skills")
    service.scan_skills()
    monkeypatch.setattr("nova.skills.tools.get_skill_service", lambda: service)

    result = await install_skill("review-skill")

    assert result.success is False
    payload = json.loads(result.content)
    assert payload == {
        "status": "error",
        "error_code": "rate_limited",
        "message": "ClawHub rate limited the download request for 'review-skill' with HTTP 429.",
        "skill_ref": "review-skill",
        "force": False,
        "skill_md_content_included": False,
        "next_action": "retry_later",
        "retry_after_seconds": 60,
    }
