# 多 Agent

Nova 通过 `delegate_to_agent` 工具支持子 Agent。主 Agent 可以把任务委派给专门的子
Agent，每个子 Agent 有自己的配置、技能和记忆。

## 工作原理

1. 主 Agent 发现某个任务适合交给专门的 Agent
2. 它带着任务描述调用 `delegate_to_agent`
3. 一个子 Agent 用自己那套 Agent 配置被拉起
4. 子 Agent 独立处理这个任务
5. 结果返回给主 Agent

## Agent 配置

Agent 存在数据库里，配置项包括：

- `agent_key` ：唯一标识
- `provider` ：用哪个 LLM 提供方
- `model` ：用哪个模型
- `instructions` ：系统提示词 / 身份

## Agent 工作区文件

每个 Agent 都可以在 `~/.nova/agents/<agent-key>/` 下有自己的工作区文件：

- `IDENTITY.md` ：Agent 身份
- `SOUL.md` ：Agent 性格
- `USER.md` ：用户画像
- `MEMORY.md` ：长期记忆

## 会话层级

子 Agent 的会话会关联到它的父会话，形成一棵会话树。这样可以共享上下文，也便于追溯。
