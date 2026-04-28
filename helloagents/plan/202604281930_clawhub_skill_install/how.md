# How

- 方案概述:
  1. 新增 `nova/skills/installer.py`，收口 ClawHub slug 规范化、远端 zip 下载、安全解压、技能根目录识别和本地安装结果返回。
  2. 在 `SkillService` 增加安装入口，安装完成后立即调用现有 `scan_skills()`，确保运行中的内存 catalog 同步更新。
  3. 在 CLI 增加 `/install-skill` 命令，参数形式为 `/install-skill <slug-or-url> [--force]`，失败时给出明确错误消息。
  4. README 补充 ClawHub 安装命令和覆盖语义，作为用户可见入口文档。

- 关键取舍:
  1. 入口取舍:
     先实现 CLI 原生命令，不把远端安装直接暴露成 LLM 默认工具，避免模型在未明确授权下主动安装远端技能。
  2. API 取舍:
     使用 ClawHub 当前公开的 slug 下载接口拉取最新 zip 包，不额外依赖外部 `clawhub` CLI 或 Node 环境。
  3. 覆盖取舍:
     默认拒绝覆盖已有目录；只有 `--force` 才删除并替换，降低本地自定义技能被误覆盖的风险。
  4. 新鲜度取舍:
     安装完成后主动刷新 catalog，而不是等下一次进程启动。

- 实施边界:
  1. 本次包含本地安装器、CLI 命令、catalog 刷新、README 和自动化测试。
  2. 本次不包含 ClawHub 搜索/浏览 UI、不包含版本选择、不包含批量安装，也不把安装能力暴露为默认 LLM tool。

- 验证方式:
  1. `tests/test_skill_installer.py` 覆盖下载解压、已存在目录拒绝安装、`--force` 覆盖替换。
  2. `tests/test_cli.py` 覆盖 `/install-skill` 参数解析、成功提示和错误提示。
  3. 回归执行现有 skills、prompt、runtime、settings 相关测试，确保安装能力没有破坏之前的技能系统。
  4. 执行 `pytest tests -q --ignore=tests/e2e` 观察更宽范围回归，并明确区分既有失败与本次变更。
