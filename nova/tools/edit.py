"""
Edit tool - perform precise file edits.
"""

import difflib
from pathlib import Path

from nova.llm import ToolResult
from nova.tools.registry import tool


@tool(
    name="edit",
    description="Precisely edit specific parts of a file by exact string matching. Use for targeted modifications without overwriting the entire file.",
    parameters={
        "type": "object",
        "properties": {
            "filePath": {
                "type": "string",
                "description": "The absolute path to the file to edit",
            },
            "oldString": {
                "type": "string",
                "description": "The exact string to replace (must match exactly, including whitespace)",
            },
            "newString": {
                "type": "string",
                "description": "The replacement string",
            },
            "replaceAll": {
                "type": "boolean",
                "description": "Replace all occurrences (default: false)",
                "default": False,
            },
        },
        "required": ["filePath", "oldString", "newString"],
    },
)
async def edit(filePath: str, oldString: str, newString: str, replaceAll: bool = False) -> ToolResult:
    p = Path(filePath)
    
    if not p.exists():
        return ToolResult(success=False, content=f"File not found: {filePath}")
    
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        
        crlf_count = content.count("\r\n")
        lf_count = content.count("\n")
        is_pure_crlf = crlf_count > 0 and crlf_count == lf_count
        
        content_norm = content.replace("\r\n", "\n")
        old_norm = oldString.replace("\r\n", "\n")
        new_norm = newString.replace("\r\n", "\n")
        
        count = content_norm.count(old_norm)
        if count == 0:
            return ToolResult(success=False, content="oldString not found. Ensure exact match including whitespace and indentation.")
        
        if count > 1 and not replaceAll:
            return ToolResult(success=False, content=f"oldString appears {count} times. Provide more context to make unique, or use replaceAll=true.")
        
        old_content_norm = content_norm
        
        if replaceAll:
            new_content_norm = content_norm.replace(old_norm, new_norm)
        else:
            new_content_norm = content_norm.replace(old_norm, new_norm, 1)
        
        if is_pure_crlf:
            final_content = new_content_norm.replace("\n", "\r\n")
            old_content_final = content
        else:
            final_content = new_content_norm
            old_content_final = content_norm
        
        if final_content and not final_content.endswith("\n"):
            final_content += "\n"

        p.write_text(final_content, encoding="utf-8")
        
        old_lines = old_content_final.splitlines(keepends=True)
        new_lines = final_content.splitlines(keepends=True)
        
        if not final_content.endswith("\n") and new_lines:
            new_lines[-1] += "\n"
        
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{p.name}",
            tofile=f"b/{p.name}",
            n=3
        ))
        
        diff_text = "".join(diff) if diff else ""
        return ToolResult(success=True, content=f"Changes applied to {p.name}:\n\n{diff_text}")
    
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = edit
