from typing import Callable


def make_seed_messages(make_msg: Callable) -> list[dict]:
    return [
        make_msg(
            "user",
            "What can you help me with today?",
        ),
        make_msg(
            "assistant",
            (
                "I can help with a wide range of tasks. Here are some examples:\n\n"
                "## Code & File Operations\n"
                "- **Read** files from your project\n"
                "- **Edit** existing code with surgical precision\n"
                "- **Write** new files and scripts\n"
                "- **Run shell commands** and review output\n\n"
                "## Search & Research\n"
                "- `grep` through your codebase\n"
                "- Search the **web** for documentation\n"
                "- Fetch URLs and extract content\n\n"
                "## Memory & Context\n"
                "I can remember facts about your project preferences"
                " and recall them later.\n\n"
                "```python\n"
                "def hello(name: str) -> str:\n"
                '    """Generate a greeting."""\n'
                '    return f"Hello, {name}!"\n'
                "```\n\n"
                "> Just ask and I'll get started!"
            ),
        ),
        make_msg(
            "tool_call",
            "Search for async Python patterns",
            tool_name="grep",
            tool_args={"pattern": "async def", "include": "*.py"},
        ),
        make_msg(
            "user",
            "Show me code examples in different languages",
        ),
        make_msg(
            "assistant",
            (
                "Here are some **JavaScript** examples:\n\n"
                "```javascript\n"
                "async function fetchUser(id) {\n"
                '  const res = await fetch(`/api/users/${id}`);\n'
                "  if (!res.ok) throw new Error('Failed to fetch');\n"
                "  return res.json();\n"
                "}\n"
                "\n"
                "const users = await Promise.all(\n"
                "  [1, 2, 3].map(fetchUser)\n"
                ");\n"
                "console.table(users);\n"
                "```\n\n"
                "And here's **TypeScript** with generics:\n\n"
                "```typescript\n"
                "interface ApiResponse<T> {\n"
                "  data: T;\n"
                "  status: number;\n"
                "  message: string;\n"
                "}\n"
                "\n"
                "async function getData<T>(\n"
                "  url: string\n"
                "): Promise<ApiResponse<T>> {\n"
                "  const res = await fetch(url);\n"
                "  return res.json();\n"
                "}\n"
                "\n"
                "type User = { id: number; name: string };\n"
                "const result = await getData<User>('/api/user');\n"
                "```\n\n"
                "JSON config example:\n\n"
                "```json\n"
                '{\n'
                '  "app": {\n'
                '    "name": "nova",\n'
                '    "version": "1.0.0",\n'
                '    "features": ["chat", "search", "tools"]\n'
                '  },\n'
                '  "logging": {\n'
                '    "level": "debug",\n'
                '    "format": "%(asctime)s %(levelname)s %(message)s"\n'
                '  }\n'
                "}\n"
                "```"
            ),
        ),
        make_msg(
            "tool_call",
            "List project files",
            tool_name="read",
            tool_args={"filePath": "src/main.py", "offset": 1, "limit": 30},
        ),
    ]
