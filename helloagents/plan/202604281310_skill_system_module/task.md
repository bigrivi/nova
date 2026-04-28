# Task

- [x] 新增 `nova/skills/` 代码目录，统一收口 scanner、catalog、service、models 等技能相关框架逻辑。
- [x] 在 `nova/skills/` 内完成 skill package 发现、frontmatter 正则解析和基础路径校验。
- [x] 扩展 `nova/settings.py`，增加 `skills_dir` 运行时路径，并明确技能数据只从目录读取。
- [x] 在运行时实现内存 skill catalog 和 `scan_skills()`，并在初始化时完成首次加载。
- [x] 在 `Agent` / `PromptBuilder` 接入 `list_skills`、`load_skill`，并改成“list_skills 读内存，`scan_skills()` 由初始化和安装技能后触发”的最小提示规则。
- [x] 让 `load_skill` 返回技能根路径，供模型后续自主使用现有文件工具读取 `scripts/`、`references/`、`assets/`。
- [x] 补齐测试：loader、prompt、runtime、完整技能调用链路，并覆盖“`scan_skills()` 后 `list_skills` 返回最新目录结果”与“不做 skill 数据库存储”边界。
- [x] 同步 `README.md`，补充技能目录约定、`SKILL.md` 结构和使用方式。
- [x] 验证：
  - `pytest tests/test_skill_loader.py tests/test_skill_flow.py tests/test_prompt.py tests/test_runtime.py tests/test_settings.py -q` -> `23 passed`
  - `pytest tests/test_integration.py tests/test_memory.py tests/test_chat_stream.py tests/test_main.py tests/test_database.py tests/test_ask_user.py tests/test_title.py -q` -> `27 passed`
  - `pytest tests -q --ignore=tests/e2e` -> `190 passed, 2 failed`
  - 未通过项仅剩 `tests/test_ui.py` 的两个现有 UI 断言，涉及 `nova/cli/ui.py`，不在本次 skill 改动范围内。
