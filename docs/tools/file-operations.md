# File Operations

## `read`

Read file contents.

```text
Read src/main.py
```

Supports optional `offset` and `limit` for reading specific line ranges.

## `write`

Create a new file or overwrite an existing one.

```text
Write a Python script called hello.py that prints "Hello, Nova!"
```

The agent generates a unified diff of the changes so you can review what was
written.

## `edit`

Precise string-match editing. The agent specifies the exact text to replace and
the new text. Supports `replaceAll` to change every occurrence of a pattern.

```text
Edit src/config.py, change "localhost" to "127.0.0.1"
```

## `glob`

Find files by name pattern, sorted by modification time (newest first).

```text
Find all Python files in the project
```

## `grep`

Search file contents using regular expressions.

```text
Search for "def handle_" in all Python files
```

Shows up to 100 matches with file paths and line numbers.

## Permissions

These tools are gated by the `tools` block in `~/.nova/permissions.json`, the same
file that configures the shell (see [Shell → Tool permissions](shell.md#tool-permissions)).
`read`/`glob`/`grep` are free inside the workspace and ask about credential paths
wherever they sit; `write`/`edit` ask when the target leaves the workspace. A
configured `deny` removes the tool entirely. Reads are free outside the workspace
by default; set `block_reads_outside_workspace: true` for the stricter posture.
