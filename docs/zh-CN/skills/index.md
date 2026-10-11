# 技能

技能用可复用的能力扩展 Nova。一个技能就是一个文件夹，里面有一个 `SKILL.md`，描述这个
技能做什么、什么时候用、需要哪些工具。

## 查找技能

让 Nova 列出可用技能：

```text
What skills do you have?
```

或者在 TUI 里用 `/install-skill` 命令。

## 安装技能

从 ClawHub（社区技能仓库）安装：

```text
Can you install the "diagram" skill?
```

Agent 会调用 `install_skill` 下载并安装它。

在 TUI 里，直接在对话中输入命令：

```text
/install-skill diagram
```

## 使用技能

装好之后，Nova 会自动把技能摘要放进系统提示词。当某个任务匹配上技能描述时，Agent 会
加载完整的技能内容并照它的指示执行。

## 创建自定义技能

技能放在 `~/.nova/skills/<skill-name>/`。一个最小技能：

```text
~/.nova/skills/my-skill/
  SKILL.md
  scripts/
  references/
```

### SKILL.md 格式

```markdown
name: My Skill
description: What this skill does
allowed_tools: shell, read, write
compatibility: gpt-4o, gemma4:26b

Full instructions for the agent go here...
```

当 Agent 判断某个技能相关时，会加载完整的 `SKILL.md` 内容。
