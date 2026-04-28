# Task

- [x] 在 `nova/skills/` 内新增 ClawHub 安装器，实现 slug 规范化、zip 下载、安全解压和本地安装结果返回。
- [x] 在 `SkillService` 中增加安装入口，并在安装成功后刷新内存技能 catalog。
- [x] 在 CLI 中新增 `/install-skill <slug-or-url> [--force]` 命令。
- [x] 默认拒绝覆盖已有技能目录，显式 `--force` 时执行替换安装。
- [x] 更新 `README.md`，补充从 ClawHub 安装技能的用法。
- [x] 补齐测试：`tests/test_skill_installer.py`、`tests/test_cli.py`。
- [x] 验证:
  - `pytest tests/test_skill_installer.py tests/test_cli.py -q` -> `62 passed`
  - `pytest tests/test_skill_loader.py tests/test_skill_flow.py tests/test_prompt.py tests/test_runtime.py tests/test_settings.py -q` -> `23 passed`
  - `pytest tests -q --ignore=tests/e2e` -> `196 passed, 2 failed`
  - 未通过项仍是既有 `tests/test_ui.py` 的两个断言失败，和本次 ClawHub 安装功能无关。
