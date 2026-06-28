# Ask User

## `ask_user`

The `ask_user` tool lets Nova ask you questions during a task. This is useful
when the agent needs clarification, confirmation, or input that only you can
provide.

## Input Types

| Type | Description |
|------|-------------|
| `text` | Single-line text input |
| `textarea` | Multi-line text input (Shift+Enter for newline) |
| `select` | Choose from a list of options |
| `confirm` | Yes/no confirmation |

## Default Values

For `text` and `textarea` inputs, the agent can provide a pre-filled default
value or template:

```
Please describe the changes you want to make:
  - Problem:
  - Solution:
  - Impact:
```

Fill in the template and submit.
