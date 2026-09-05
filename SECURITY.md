# Security Policy

## Reporting a vulnerability

Please do not open a public issue for security vulnerabilities.

Use GitHub's private vulnerability reporting instead. Go to the **Security** tab at the top of this repository and click **Report a vulnerability**. That creates a private advisory visible only to you and the maintainers, so details stay out of public view until a fix is ready.

Do not include sensitive data in public comments, issues, or pull requests.

## Supported versions

Nova has no release tags yet and no `CHANGELOG.md`. The version in `nova/__init__.py` is `1.0.0`, but the project is pre-1.0 in practice.

Only the latest commit on `main` is supported. If you are reporting a problem, please confirm it reproduces on current `main`.

## Security posture

Nova runs on your machine with your privileges. It is not sandboxed, containerised, or isolated at the OS level. Agent tools and shell commands execute locally as your user.

See `docs/advanced/security.md` for the full threat model. In short:

* **Shell commands are pattern matched into three tiers.** Blocked outright, requires user approval, or auto-runs. Tier 1 is hardline blocked and never reaches the approval prompt, tier 2 asks for approval over SSE and is answered via `POST /api/chat/approve`, tier 3 runs right away. Classification is pattern based, not a sandbox or container boundary.
* **There is no container or OS-level sandbox.** Treat every shell and `code_run` invocation as code running on your host with your file and network access.
* **Tool guardrails are heuristic.** The agent halts after 5 identical tool calls in a row or 3 identical failures, and warns after 10 read only calls without a write. Prompt injection patterns are scanned in user messages, saved memories, and workspace persona files, but this is best effort pattern matching.
* **Workspace matters.** The per-session workspace directory scopes file tools like `read`, `write`, `glob`, `grep`, `shell`, and `code_run`, but an explicit `cwd` still wins and tools can reach absolute paths and the network. Point a session at a directory you are comfortable letting the agent read, write, and execute in.

## Secrets handling

API keys for providers are stored in plaintext in `~/.nova/config.json`, under `NOVA_HOME` if you have overridden the home directory. Nova does not restrict that file's permissions: it is created with your system defaults, which on a typical Unix system means `0644` and therefore readable by other local users. It is not encrypted. On a shared machine, tighten it yourself with `chmod 600 ~/.nova/config.json`. Do not paste that file or raw logs in public issues without redacting keys. Logs live at `~/.nova/logs/nova.log` (file only, daily rotation, 30-day retention) and may contain request details.

When you report a vulnerability or a bug that includes config or logs, redact keys and tokens first.
