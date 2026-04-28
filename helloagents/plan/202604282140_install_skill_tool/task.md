# Task

- [x] 新增 `install_skill` 内置工具，调用现有 ClawHub 安装链路把远端技能安装到 `NOVA_HOME/skills`。
- [x] 保持技能相关逻辑继续收口在 `nova/skills/`，CLI 安装命令不改现有行为。
- [x] 在 prompt 中补最小边界，明确只有用户显式要求安装技能时才调用 `install_skill`。
- [x] 收口重扫时机：`scan_skills()` 只在初始化和安装技能成功后触发，不由 `write/edit` 自动触发。
- [x] 进一步收紧安装边界：不确定本地是否已安装时先 `list_skills`，若已存在且用户未要求更新则优先 `load_skill`。
- [x] 强化初始技能发现提示：当用户提到技能、询问可用技能或任务像可复用工作流时，优先先 `list_skills`。
- [x] 在系统提示词中直接注入当前可用技能摘要，降低模型遗漏技能发现的概率。
- [x] `install_skill` 返回结构化安装元数据，不返回完整 `SKILL.md` 内容，避免大文本进入工具结果。
- [x] CLI 不显示 `install_skill` 的工具结果内容，只保留工具调用动作，避免安装元数据污染终端输出。
- [x] 补齐测试，覆盖工具注册、prompt 规则、成功安装与失败返回。
- [x] 验证:
  - `pytest tests/test_prompt.py tests/test_runtime.py -q` -> `13 passed`
  - `pytest tests/test_skill_loader.py tests/test_skill_flow.py tests/test_nova.py tests/test_integration.py -q` -> `13 passed`
