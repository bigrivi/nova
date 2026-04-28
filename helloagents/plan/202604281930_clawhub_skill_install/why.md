# Why

- 背景:
  当前 `nova` 已经具备本地技能目录扫描、内存 catalog、`list_skills` 和 `load_skill`，但还缺少一个把远端技能拉到 `NOVA_HOME/skills` 的官方入口，用户无法直接从 ClawHub 安装可用技能。
- 目标:
  增加一条最小可用的 ClawHub 安装链路，让 CLI 可以按技能 slug 或技能页面 URL 下载最新技能包、落盘到本地技能目录，并在当前运行时立即刷新可用技能列表。
- 成功标准:
  1. CLI 提供显式安装命令，能接收技能 slug 或 ClawHub 技能页面 URL。
  2. 安装逻辑统一收口在 `nova/skills/`，不把远端安装流程散落到 CLI 里。
  3. 安装后本地 `NOVA_HOME/skills` 目录可直接被现有 `scan_skills()` / `list_skills` / `load_skill` 使用。
  4. 默认不覆盖已有同名本地技能目录，只有显式 `--force` 才替换。
  5. 需要有针对下载、解压、覆盖安装和 CLI 接线的自动化测试。
- 约束与风险:
  1. 技能相关逻辑必须继续放在 `nova/skills/`。
  2. 不引入新的 YAML、marketplace SDK 或数据库依赖，继续使用现有 `httpx` 和标准库 `zipfile`。
  3. 远端 zip 包需要做路径安全校验，避免目录逃逸或多 skill 混装。
  4. ClawHub API 采用当前官方文档可见的 slug 下载方式，若未来 API 形态变化，需要单独调整安装器。
