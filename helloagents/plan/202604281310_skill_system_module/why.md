# Why

- 背景:
  `spec.md` 第 11 节定义了遵循 agentskills.io 形态的技能系统，包括 `SKILL.md` frontmatter、渐进式加载和技能资源目录；但当前 `nova` 运行时只有工具调用与 memory 模块，没有技能发现、加载和 prompt 注入链路。
- 目标:
  在不推翻现有 provider function-calling tool loop 的前提下，为 `nova` 增加一套一等技能模块，使模型能够从内存里的技能 catalog 获取当前可用技能，再按需加载完整 `SKILL.md`，而这个 catalog 由初始化和目录变动时的独立 `scan_skills()` 从技能目录重建，不引入技能数据库存储。
- 成功标准:
  1. 运行时能从约定目录发现 skill package，并解析 `SKILL.md` 元数据。
  2. 模型可通过 `list_skills` 获取当前内存中的可用技能摘要；初始化完成后可用，目录变动后经刷新函数更新。
  3. 模型可通过 `load_skill` 获取技能根路径和完整 `SKILL.md`，再自主决定是否使用现有文件工具读取 `references/`、`scripts/`、`assets/` 下资源。
  4. 技能定义、元数据和目录扫描结果不写入数据库，不做 skill catalog sync/cache/upsert。
  5. 现有 tool-calling、memory、session 流程不回退，相关测试可覆盖新链路。
- 约束与风险:
  1. 仓库当前没有 skill 模块，也没有 `skills` 目录约定，需补最小路径与元数据规范。
  2. 当前 Agent 只支持 provider 原生 tool calling，不支持 spec 里的独立 `skill_call` JSON action loop；若强行重写，会明显放大回归面。
  3. `SKILL.md` 的 frontmatter 不引入 YAML 解析依赖，只按受限字段集合用正则表达式解析；这要求 frontmatter 结构保持简单、稳定、可预测。
  4. 不做 skill catalog 入库，但接受 `load_skill` 结果作为普通会话消息进入消息表，因为后续轮次仍需要把这些消息继续喂给 LLM。
  5. 技能框架代码与运行时技能内容需要分清：这里按“代码放 `nova/skills/`，用户技能内容放 `NOVA_HOME/skills`”收口，避免把框架实现和技能资产混在同一物理目录。
