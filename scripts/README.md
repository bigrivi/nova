# 权限策略端到端验证

Nova 的权限系统有两层测试，**这一层覆盖单层覆盖不到的部分**。

## 为什么不在 `tests/` 下

它会启动真实的 Nova 服务器、监听随机端口、调用真实模型。
放进 `tests/` 意味着 `pytest tests/` 会尝试收它 —— 而单元测试套件必须是离线可跑、
秒级完成的。所以它是脚本，不是 pytest 用例。

同时它**曾经只存在于 `/tmp`**，那次机器重启就没了，`git log` 显示它从未进过仓库。
它覆盖的是整条接线（SSE 流、HTTP 审批往返、`ToolsetBuilder.build()`），
而那次 `_register_tool_policies` 冲掉图片提取的静默回归，单测 1546 条全绿也没抓到。

## 跑法

```bash
# 只跑进程内检查：无服务器、无模型、无网络，秒级完成。CI 用这个。
.venv/bin/python scripts/policy_e2e.py --local-only

# 全量：9 个场景，每个独立 NOVA_HOME 与随机端口
.venv/bin/python scripts/policy_e2e.py

# 挑场景
.venv/bin/python scripts/policy_e2e.py --list
.venv/bin/python scripts/policy_e2e.py --only V0 --only V4
```

全量需要 `~/.nova/config.json` 里有可用的 provider/model（默认
`opencode_zen_free:space-bunny-free`，免费额度会限流 —— 脚本在场景之间有 4 秒间隔，
并且每个场景失败会重试一次）。

## 覆盖什么

| 层 | 内容 |
|---|---|
| `V0` | 出厂默认：无规则放行、ask 询问、工作区豁免、工作区外询问 |
| `V1`–`V4` | `permissions.json` 的 `allow` / `disable` / `ask`，以及 `allow` 够不到 block |
| `V5`–`V7` | 工具轴 `ask` / `deny` / 命名空间，`*` deny 时 shell 始终豁免 |
| `V8` | 两个轴同时生效 |
| 进程内 | 接口覆盖不到的部分：复核的三态、复核否决与已有授权的冲突、sub-agent 无通道、工具策略最长前缀胜出、配置文件损坏回落、授权范围 |

## 期望

```
18 项：18 通过，0 失败，0 跳过，0 harness 错误
```

全量模式的跳过项是模型拒绝执行破坏性命令（`rm -rf /`），不是策略问题。

## 维护

新增规则时，`--local-only` 里加一条断言。它比单元测试慢不到一秒，
但它经过真实的 `ShellToolBehavior` 与 `decide`，而不是手工拼的 registry。