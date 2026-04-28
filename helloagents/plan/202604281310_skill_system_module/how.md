# How

- 方案概述:
  1. 新增 `nova/skills/` 包，统一承载所有框架侧技能逻辑。包内提供 `models.py`、`scanner.py`、`catalog.py`、`service.py` 等模块：`scanner` 负责发现与解析 skill package，`catalog/service` 负责维护内存中的技能 catalog，并统一封装 `list_skills` / `load_skill` 这类运行时读取动作。
  2. 扩展 `nova/settings.py`，新增 `skills_dir` 运行时路径，默认落在 `NOVA_HOME/skills`，与现有 `workspace`、`logs`、`nova.db` 一样归属用户运行时目录。
  3. 技能定义和元数据来源仍然只有文件系统，不写入数据库；运行时维护一份内存 catalog，供 `list_skills` 直接返回。
  4. 在 Agent 启动时动态注册两个技能工具：
     - `list_skills()`: Level 1，直接返回当前内存 catalog 中的技能摘要，例如 `name`、`description`、`path`。
     - `load_skill(skill_name)`: Level 2，按 `skill_name` 读取完整 `SKILL.md`，完成校验后把 `skill_name`、技能根路径、完整正文返回给模型。
  5. 新增内部 `scan_skills()`：负责扫描运行时技能目录并重建内存 catalog。初始化时调用一次；安装技能成功后再次调用。
  6. `load_skill` 默认根据当前内存 catalog 解析目标技能路径，再读取对应 `SKILL.md` 正文。
  7. 资源目录 `scripts/`、`references/`、`assets/` 不新增专用工具；模型在拿到技能根路径后，使用现有 `read`、`glob`、`grep`、`bash` 等通用工具自主决定何时继续读取。
  8. `PromptBuilder` 不再注入静态 `Available Skills` 列表，只保留最小规则：需要当前技能清单时调用 `list_skills`，需要技能全文时调用 `load_skill`。
  9. 保持现有 provider-native function calling 主循环不变，不新增 spec 式独立 `skill_call` 事件类型；技能在调度层以工具形式触发，在运行时内部仍由 `skill` 模块负责。
  10. `load_skill` 返回的完整 `SKILL.md` 允许作为普通 `tool` 消息进入现有会话消息链路，以便后续轮次继续把这些消息喂给 LLM；这不视为 skill 数据入库，只是沿用现有对话历史持久化。

- 关键取舍:
  1. 调度取舍:
     采用“技能模块 + 技能工具入口”，不重写 Agent 为 JSON `skill_call` action loop。这样能复用现有 `ToolCall -> ToolResult -> next LLM turn` 链路，避免动到 provider、CLI、server 的主协议。
  2. 路径取舍:
     框架代码层统一收口到 `nova/skills/`；运行时技能内容目录仍放在 `NOVA_HOME/skills`。这样“技能相关逻辑在 skills 目录”与“技能内容来自用户运行时目录”两个要求可以同时成立。
  3. 解析取舍:
     不引入 YAML 解析依赖；`SKILL.md` frontmatter 只支持当前方案实际需要的受限字段，并用正则表达式解析。首批字段按 `name`、`description`、`compatibility`、`allowed-tools` 收口，暂不支持任意嵌套对象。
  4. 上下文取舍:
     不把技能列表静态塞进 prompt；技能清单与全文都按工具结果进入最近对话，减少上下文膨胀。
  5. 资源访问取舍:
     不再增加 `load_skill_resource` 这类技能专用资源工具，避免与现有通用文件工具职责重叠；`load_skill` 只负责把技能正文和根路径暴露给模型，后续文件探索由模型自行决定。
  6. 存储取舍:
     不引入 skill 相关数据库表、同步任务或会话级 skill 持久化状态；技能目录只在初始化和目录变动时刷新到内存 catalog。`load_skill` 的正文结果允许按普通会话消息持久化。
  7. 新鲜度取舍:
     `list_skills` 返回内存 catalog，调用成本低且结果稳定；catalog 的新鲜度由初始化和安装技能后的 `scan_skills()` 保证，而不是让 `list_skills` 每次直接扫盘，也不由 `write/edit` 自动触发重扫。

- 实施边界:
  1. 本次包含 `nova/skills/` 代码目录收口、skill package 发现、frontmatter 解析、内存 catalog、`scan_skills()`、`list_skills`、按需 `load_skill`、最小 prompt 规则、文档与测试。
  2. 本次不包含 remote skill marketplace、技能安装/升级命令、自动执行 skill `scripts/`、独立 `skill_call` SSE 事件、或基于技能的二级子 Agent loop。
  3. `compatibility` 字段本次只做展示与基础校验提示，不做复杂环境求解。
  4. `scripts/`、`references/`、`assets/` 的具体文件访问继续复用现有通用工具，不新增 skill 专用资源协议。
  5. 不实现 skill catalog 入库、skill metadata 入库、或 `active_skills` 一类 session 持久化字段。

- 验证方式:
  1. `tests/test_skill_loader.py`:
     覆盖技能发现、frontmatter 正则解析、非法目录/缺失 `SKILL.md`、catalog 构建、`list_skills` 摘要结果，以及 `load_skill` 返回的根路径信息。
  2. `tests/test_prompt.py`:
     覆盖最小 prompt 规则，明确模型需要最新技能清单时应调用 `list_skills`。
  3. `tests/test_runtime.py`:
     覆盖 `skills_dir` 默认路径，以及运行时不会尝试做 skill 数据库存储。
  4. `tests/test_integration.py` 或新增 `tests/test_skill_flow.py`:
     使用 fake provider 模拟 `list_skills` -> `load_skill` -> 后续通用文件工具读取 skill 目录文件 -> 最终回答 的完整链路。
  5. 动态变更回归:
     在测试内先创建一组 skill，构建初始 catalog，再新增/删除 skill 目录并触发 `scan_skills()`，验证后续 `list_skills` 返回已更新结果。

- 风险缓解:
  1. 上下文膨胀:
     prompt 不内嵌技能清单；技能摘要只在 `list_skills` 调用轮次进入上下文，技能全文在 `load_skill` 后会进入会话消息链路，必要时仍需依赖后续 compaction 控制体积。
  2. 目录逃逸:
     `load_skill` 返回路径时统一使用规范化绝对路径；后续文件访问继续由现有文件工具自身的路径约束负责。
  3. 工具不匹配:
     `load_skill` 时比对 `allowed-tools` 与当前 registry，若有缺失，在工具结果中明确警告但不崩溃。
  4. 回滚成本:
     新能力主要新增于 `nova/skills/` 和少量接线文件，若要回退，可整体移除技能模块与工具注册，不影响既有 memory/tool loop。

⚠️ 正则解析边界:
frontmatter 解析只承诺支持受限字段和简单格式。如果后续要支持复杂 YAML 语法、深层嵌套对象或多行自由结构，需要重新评估解析策略，而不是继续堆正则兼容。

⚠️ 不确定因素: `spec.md` 的执行循环使用独立 `skill_call` 动作，而当前实现完全建立在 provider function-calling 上。本方案的假设是“先实现技能作为一等模块，但调度层复用现有 tool call 协议”。如果你要求严格实现独立 `skill_call` 协议，需要额外重写 Agent loop、事件语义和 server/CLI 展示链路，范围会显著扩大。
