"""How to invoke a shell: detect it, build its argv, translate a path.

Shared rather than owned. ``tasks.executors.shell`` uses all three, and so does the
shell tool -- which does not spawn anything itself, but hands a resolved ``cwd``
down to that executor. Two callers that must agree on where a command runs is the
reason this is one module: the workspace exemption is judged against the workspace
while the command executes against this cwd, and those only agree if both sides
derive it the same way.

``get_shell_label`` is the odd one out, used only by the prompt builder to describe
the environment to the model. It stays because it is a four-line wrapper over
``detect_shell``; moving it would mean importing the detection from here anyway,
under a second name, for no gain in the import graph.
"""

import functools
import os
import re
import shutil
import sys


@functools.cache
def detect_shell() -> tuple[str, str]:
    """Detect the best available shell.

    Returns:
        tuple of (executable_path, display_name)
    """
    if sys.platform == "win32":
        return _detect_windows_shell()
    return _detect_unix_shell()


def _detect_windows_shell() -> tuple[str, str]:
    pwsh = shutil.which("pwsh.exe")
    if pwsh:
        return (pwsh, "pwsh")

    ps = shutil.which("powershell.exe")
    if ps:
        return (ps, "powershell")

    git = shutil.which("git.exe")
    if git:
        bash = os.path.join(os.path.dirname(os.path.dirname(git)), "bin", "bash.exe")
        if os.path.exists(bash):
            return (bash, "bash")

    comspec = os.environ.get("COMSPEC")
    if comspec and os.path.exists(comspec):
        return (comspec, "cmd")

    return ("cmd.exe", "cmd")


def _detect_unix_shell() -> tuple[str, str]:
    shell = os.environ.get("SHELL")
    if shell and os.path.exists(shell):
        return (shell, _extract_name(shell))

    if sys.platform == "darwin":
        zsh = "/bin/zsh"
        if os.path.exists(zsh):
            return (zsh, "zsh")

    for path in ["/bin/bash", "/bin/zsh", "/bin/sh"]:
        if os.path.exists(path):
            return (path, _extract_name(path))

    return ("/bin/sh", "sh")


def _extract_name(path: str) -> str:
    name = os.path.basename(path).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def build_shell_args(shell_path: str, command: str) -> list[str]:
    """Build argument list for the given shell to execute a command."""
    name = _extract_name(shell_path)

    if name in ("bash", "zsh"):
        return ["-l", "-c", command]
    if name in ("pwsh", "powershell"):
        return ["-NoProfile", "-Command", command]
    if name == "cmd":
        return ["/c", command]

    return ["-c", command]


def normalize_path(path: str) -> str:
    """Translate Unix-style paths to Windows native paths (no-op on Unix)."""
    if sys.platform != "win32":
        return path

    path = re.sub(
        r"^/([a-zA-Z])/(.*)",
        lambda m: f"{m.group(1).upper()}:/{m.group(2)}",
        path,
    )
    path = re.sub(
        r"^/mnt/([a-zA-Z])/(.*)",
        lambda m: f"{m.group(1).upper()}:/{m.group(2)}",
        path,
    )
    path = re.sub(
        r"^/cygdrive/([a-zA-Z])/(.*)",
        lambda m: f"{m.group(1).upper()}:/{m.group(2)}",
        path,
    )

    return path


def get_shell_label() -> str:
    """Return a human-readable label for the current platform and shell."""
    _, name = detect_shell()
    os_name = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(
        sys.platform, sys.platform
    )
    return f"{os_name} ({name})"
