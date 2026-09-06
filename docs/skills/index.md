# Skills

Skills extend Nova with reusable capabilities. A skill is a folder containing a
`SKILL.md` file that describes what the skill does, when to use it, and which
tools it needs.

## Finding Skills

Ask Nova to list available skills:

```text
What skills do you have?
```

Or use the `/install-skill` command in the TUI.

## Installing Skills

From ClawHub (the community skill repository):

```text
Can you install the "diagram" skill?
```

The agent calls `install_skill` to download and install it.

From the TUI, type the command in chat:

```text
/install-skill diagram
```

## Using Skills

Once installed, Nova automatically includes skill summaries in its system prompt.
When a task matches a skill's description, the agent loads the full skill
content and follows its instructions.

## Creating Custom Skills

Skills live in `~/.nova/skills/<skill-name>/`. A minimal skill:

```text
~/.nova/skills/my-skill/
  SKILL.md
  scripts/
  references/
```

### SKILL.md Format

```markdown
name: My Skill
description: What this skill does
allowed_tools: shell, read, write
compatibility: gpt-4o, gemma4:26b

Full instructions for the agent go here...
```

The agent loads the full `SKILL.md` content when it decides the skill is
relevant.
