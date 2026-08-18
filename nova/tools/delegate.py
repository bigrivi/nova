"""
Delegate tool - delegate tasks to sub-agents.
"""

import asyncio
import logging
from typing import Optional

from nova.llm import ToolResult
from nova.tools.registry import tool

log = logging.getLogger(__name__)


@tool(
    name="delegate_to_agent",
    description="Delegate a task to a sub-agent. The sub-agent will execute the task independently and return the result.",
    parameters={
        "type": "object",
        "properties": {
            "agent_key": {
                "type": "string",
                "description": "The key of the agent to delegate to (e.g., 'code-review', 'testing')",
            },
            "task": {
                "type": "string",
                "description": "The task description for the sub-agent to execute",
            },
            "context": {
                "type": "string",
                "description": "Additional context or instructions for the sub-agent (optional)",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 300)",
                "default": 300,
            },
        },
        "required": ["agent_key", "task"],
    },
)
async def delegate_to_agent(
    agent_key: str,
    task: str,
    context: Optional[str] = None,
    timeout: int = 300,
) -> ToolResult:
    """
    Delegate a task to a sub-agent.
    
    Args:
        agent_key: The key of the agent to delegate to
        task: The task description for the sub-agent to execute
        context: Additional context or instructions for the sub-agent
        timeout: Timeout in seconds (default: 300)
    
    Returns:
        ToolResult with the sub-agent's response
    """
    try:
        from nova.app.runtime import build_agent
        from nova.session.manager import get_session_manager
        from nova.db import get_default_data_source
        
        log.info(f"Delegating task to agent '{agent_key}': {task[:100]}...")
        
        # 1. 获取当前会话的 agent_key（父 agent）
        session_manager = get_session_manager()
        current_session = session_manager.get_current_session()
        parent_session_id = current_session.id if current_session else None
        
        # 2. 验证父子关系（支持多父 agent）
        data_source = await get_default_data_source()
        target_agent = await data_source.get_agent(agent_key)
        if target_agent:
            parent_keys = await data_source.get_agent_parents(agent_key)
            current_agent_key = current_session.agent_key if current_session else None

            if parent_keys and current_agent_key not in parent_keys:
                log.warning(f"Agent '{agent_key}' is not a child of agent '{current_agent_key}'")
        
        # 3. 构建子 agent
        sub_agent = await build_agent(agent_key=agent_key)
        
        # 4. 准备任务消息
        task_message = task
        if context:
            task_message = f"{task}\n\nAdditional context:\n{context}"
        
        # 5. 创建子会话，传递 parent_id 建立父子关系
        session = await session_manager.create_session(
            persist=True,
            first_message=task_message,
            agent_key=agent_key,
            parent_id=parent_session_id,
        )
        session_id = session.id
        
        # 6. 执行任务（传递 session_id，避免创建第二个 session）
        result_content = ""
        error_message = None
        
        try:
            async with asyncio.timeout(timeout):
                async for event, data in sub_agent.chat_stream(
                    user_input=task_message,
                    session_id=session_id,
                ):
                    if event.value == "done":
                        if isinstance(data, dict):
                            result_content = data.get("content", "")
                            reason = data.get("reason", "")
                            if reason != "completed":
                                error_message = f"Task ended with reason: {reason}"
                        break
                    elif event.value == "error":
                        error_message = f"Agent error: {data}"
                        break
                    elif event.value == "text_delta":
                        # Accumulate text content
                        if isinstance(data, str):
                            result_content += data
        
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                content=f"Task delegation timed out after {timeout} seconds",
            )
        
        if error_message:
            return ToolResult(
                success=False,
                content=f"Sub-agent error: {error_message}",
            )
        
        if not result_content:
            return ToolResult(
                success=False,
                content="Sub-agent returned empty result",
            )
        
        log.info(f"Sub-agent '{agent_key}' completed task successfully")
        return ToolResult(
            success=True,
            content=f"Sub-agent '{agent_key}' completed the task:\n\n{result_content}",
        )
        
    except Exception as e:
        log.error(f"Failed to delegate task to agent '{agent_key}': {e}")
        return ToolResult(
            success=False,
            content=f"Failed to delegate task: {str(e)}",
        )


TOOL = delegate_to_agent
