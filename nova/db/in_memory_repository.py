from __future__ import annotations

import time
import uuid
import json
from typing import Any, Optional

from nova.db.repository import NovaRepository
from nova.session.models import Message, MessageFilter


class InMemoryRepository(NovaRepository):
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._messages: dict[str, Message] = {}
        self._agents: dict[str, dict[str, Any]] = {
            "main": {
                "key": "main",
                "name": "Main",
                "description": "",
                "model": "gpt-4o",
                "provider": "openai",
                "tools": None,
                "workspace_dir": None,
                "parent_id": None,
                "created_at": int(time.time() * 1000),
                "updated_at": int(time.time() * 1000),
            }
        }
        self._agent_parents: set[tuple[str, str]] = set()
        self._memories: dict[str, dict[str, Any]] = {}
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    async def save_session(self, session: Any) -> None:
        now = int(time.time() * 1000)
        self._sessions[session.id] = {
            "id": session.id,
            "agent_key": getattr(session, "agent_key", "main"),
            "title": getattr(session, "title", None),
            "parent_id": getattr(session, "parent_id", None),
            "workspace_dir": getattr(session, "workspace_dir", None),
            "summary_goal": getattr(session, "summary_goal", None),
            "summary_accomplished": getattr(session, "summary_accomplished", None),
            "summary_remaining": getattr(session, "summary_remaining", None),
            "created_at": self._milliseconds(getattr(session, "created_at", now)),
            "updated_at": self._milliseconds(getattr(session, "updated_at", now)),
            "compacted_at": getattr(session, "compacted_at", None),
            "message_count": getattr(session, "message_count", 0),
            "turn_count": getattr(session, "turn_count", 0),
            "metadata": json.dumps(getattr(session, "metadata", None)) if getattr(session, "metadata", None) else None,
        }

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        return dict(session) if session else None

    async def update_session_title(self, session_id: str, title: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session["title"] = title
        return True

    async def set_session_workspace(self, session_id: str, workspace_dir: str | None) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session["workspace_dir"] = workspace_dir
        return True

    async def delete_session(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        for message_id in [m.id for m in self._messages.values() if m.session_id == session_id]:
            del self._messages[message_id]
        return True

    async def get_all_sessions(self, limit: int = 50, agent_key: str | None = None) -> list[dict]:
        sessions = list(self._sessions.values())
        if agent_key:
            sessions = [s for s in sessions if s["agent_key"] == agent_key]
        sessions.sort(key=lambda item: item["updated_at"], reverse=True)
        return [dict(session) for session in sessions[:limit]]

    async def get_sessions_by_parent_id(self, parent_id: str, limit: int = 50) -> list[dict]:
        sessions = [s for s in self._sessions.values() if s["parent_id"] == parent_id]
        sessions.sort(key=lambda item: item["created_at"], reverse=True)
        return [dict(session) for session in sessions[:limit]]

    async def add_message(self, session_id: str, role: str, content: str, **kwargs: Any) -> Message:
        message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=kwargs.get("tool_calls"),
            tool_call_id=kwargs.get("tool_call_id"),
            summary=1 if kwargs.get("summary", False) else 0,
            images=kwargs.get("images"),
            reasoning_content=kwargs.get("reasoning_content"),
            group_id=kwargs.get("group_id"),
            reasoning_elapsed_ms=kwargs.get("reasoning_elapsed_ms"),
            provider_meta=kwargs.get("provider_meta"),
            model=kwargs.get("model"),
            tokens_input=kwargs.get("tokens_input"),
            tokens_output=kwargs.get("tokens_output"),
        )
        self._messages[message.id] = message
        session = self._sessions.get(session_id)
        if session:
            session["updated_at"] = message.time_created
            session["message_count"] += 1
        return message

    async def get_messages(self, session_id: str, msg_filter: MessageFilter | None = None) -> list[Message]:
        filter_value = msg_filter or MessageFilter()
        messages = [m for m in self._messages.values() if m.session_id == session_id]
        messages.sort(key=lambda message: message.time_created)
        if not filter_value.include_compacted:
            messages = [m for m in messages if m.compacted == 0]
        if filter_value.exclude_tool_role:
            messages = [m for m in messages if m.role != "tool"]
        if filter_value.only_non_summary:
            messages = [m for m in messages if m.summary == 0]
        if filter_value.limit is not None:
            messages = messages[:filter_value.limit]
        return messages

    async def compress_messages(self, session_id: str, target_count: int = 50) -> None:
        messages = await self.get_messages(session_id, MessageFilter(include_compacted=True))
        if len(messages) <= target_count:
            return
        delete_count = len(messages) - target_count
        for message in [m for m in messages if m.summary == 0][:delete_count]:
            message.summary = 1
        session = self._sessions.get(session_id)
        if session:
            session["compacted_at"] = int(time.time() * 1000)

    async def mark_messages_compacted(self, session_id: str) -> None:
        for message in self._messages.values():
            if message.session_id == session_id and message.compacted == 0 and message.summary == 0:
                message.compacted = 1

    async def mark_messages_compacted_by_ids(self, session_id: str, message_ids: list[str]) -> None:
        for message_id in message_ids:
            message = self._messages.get(message_id)
            if message and message.session_id == session_id:
                message.compacted = 1

    async def update_session_compacted_at(self, session_id: str, timestamp: int) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["compacted_at"] = timestamp

    async def update_message_content(self, message_id: str, content: str) -> None:
        message = self._messages.get(message_id)
        if message:
            message.content = content
            message.data = content

    async def delete_messages(self, session_id: str, message_ids: list[str]) -> int:
        selected = [m for m in self._messages.values() if m.session_id == session_id and m.id in message_ids]
        for message in selected:
            del self._messages[message.id]
        session = self._sessions.get(session_id)
        if session:
            session["message_count"] = max(0, session["message_count"] - len(selected))
            session["updated_at"] = int(time.time() * 1000)
        return len(selected)

    async def list_agents(self) -> list[dict]:
        return sorted((dict(agent) for agent in self._agents.values()), key=lambda item: item["name"])

    async def get_agent(self, key: str) -> dict[str, Any] | None:
        agent = self._agents.get(key)
        return dict(agent) if agent else None

    async def save_agent(self, agent: dict[str, Any]) -> None:
        self._agents[agent["key"]] = dict(agent)

    async def get_child_agents(self, parent_key: str) -> list[dict]:
        return [agent for agent in await self.list_agents() if agent.get("parent_id") == parent_key]

    async def get_agent_parents(self, child_key: str) -> list[str]:
        return [parent for child, parent in self._agent_parents if child == child_key]

    async def get_agent_children(self, parent_key: str) -> list[str]:
        return [child for child, parent in self._agent_parents if parent == parent_key]

    async def set_agent_parents(self, child_key: str, parent_keys: list[str]) -> None:
        self._agent_parents = {(child, parent) for child, parent in self._agent_parents if child != child_key}
        self._agent_parents.update((child_key, parent) for parent in parent_keys)

    async def add_agent_parent(self, child_key: str, parent_key: str) -> None:
        self._agent_parents.add((child_key, parent_key))

    async def remove_agent_parent(self, child_key: str, parent_key: str) -> None:
        self._agent_parents.discard((child_key, parent_key))

    async def delete_agent(self, key: str) -> bool:
        if key not in self._agents:
            return False
        del self._agents[key]
        self._agent_parents = {(child, parent) for child, parent in self._agent_parents if child != key and parent != key}
        for session_id in [s["id"] for s in self._sessions.values() if s["agent_key"] == key]:
            await self.delete_session(session_id)
        return True

    async def save_memory(self, record: Any) -> None:
        self._memories[record.id] = {
            "id": record.id,
            "key": record.key,
            "scope": record.scope,
            "session_id": record.session_id,
            "memory_type": record.memory_type,
            "content": record.content,
            "summary": record.summary,
            "tags": json.dumps(record.tags) if record.tags else None,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def get_memory_by_key(self, key: str, scope: str, session_id: str | None = None) -> dict[str, Any] | None:
        for memory in self._memories.values():
            if memory["key"] != key or memory["scope"] != scope:
                continue
            if scope == "session" and session_id is None:
                continue
            if scope != "session" or memory["session_id"] == session_id:
                return dict(memory)
        return None

    async def list_memories(self, filters: Any) -> list[dict]:
        memories = list(self._memories.values())
        if filters.scope != "all":
            memories = [m for m in memories if m["scope"] == filters.scope]
        if filters.memory_type:
            memories = [m for m in memories if m["memory_type"] == filters.memory_type]
        if filters.session_id:
            memories = [m for m in memories if m["scope"] != "session" or m["session_id"] == filters.session_id]
        memories.sort(key=lambda item: item["updated_at"], reverse=True)
        return [dict(memory) for memory in memories[:filters.limit]]

    async def delete_memory_by_id(self, memory_id: str) -> int:
        return 1 if self._memories.pop(memory_id, None) is not None else 0

    async def delete_memories_by_session(self, session_id: str) -> int:
        ids = [key for key, memory in self._memories.items() if memory["session_id"] == session_id]
        for memory_id in ids:
            del self._memories[memory_id]
        return len(ids)

    async def list_memories_by_session(self, session_id: str) -> list[dict]:
        memories = [dict(m) for m in self._memories.values() if m["session_id"] == session_id]
        memories.sort(key=lambda item: item["updated_at"], reverse=True)
        return memories

    async def delete_memory_by_key(self, key: str, scope: str, session_id: str | None = None) -> int:
        memory = await self.get_memory_by_key(key, scope, session_id)
        return await self.delete_memory_by_id(memory["id"]) if memory else 0

    @staticmethod
    def _milliseconds(value: Any) -> int:
        return int(value.timestamp() * 1000) if hasattr(value, "timestamp") else int(value)
