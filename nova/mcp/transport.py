from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

log = logging.getLogger(__name__)

_MCP_VERSION = "2025-03-26"


class McpError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"[{code}] {message}")


class McpTransport(ABC):
    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def send_request(self, method: str, params: dict | None = None) -> dict:
        ...

    @abstractmethod
    async def send_notification(self, method: str, params: dict | None = None) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


class StdioTransport(McpTransport):
    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None):
        self._command = command
        self._args = args or []
        self._env = env or {}
        self._process: Optional[asyncio.subprocess.Process] = None
        self._pending: dict[str, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._request_id = 0

    def _next_id(self) -> str:
        self._request_id += 1
        return str(self._request_id)

    async def connect(self) -> None:
        merged_env = {**os.environ, **self._env}
        self._process = await asyncio.create_subprocess_exec(
            self._command, *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._start_stderr_reader()

    def _start_stderr_reader(self) -> None:
        async def _read_stderr():
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                log.debug("MCP stderr: %s", line.decode().rstrip())
        asyncio.create_task(_read_stderr())

    async def send_request(self, method: str, params: dict | None = None) -> dict:
        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        self._process.stdin.write((json.dumps(payload) + "\n").encode())
        await self._process.stdin.drain()
        result = await asyncio.wait_for(future, timeout=120)
        if "error" in result:
            err = result["error"]
            raise McpError(err.get("code", 0), err.get("message", str(err)))
        return result.get("result", {})

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        self._process.stdin.write((json.dumps(payload) + "\n").encode())
        await self._process.stdin.drain()

    async def _read_stdout(self) -> None:
        while True:
            line = await self._process.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            req_id = msg.get("id")
            if req_id and req_id in self._pending:
                self._pending.pop(req_id).set_result(msg)
            elif req_id:
                log.debug("MCP got response for unknown request %s", req_id)
            else:
                log.debug("MCP notification: %s", msg.get("method", msg))

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()


class HttpTransport(McpTransport):
    def __init__(self, url: str, headers: dict[str, str] | None = None, timeout: int = 120):
        self._url = url
        self._headers = headers or {}
        self._timeout = timeout
        self._session: Optional[Any] = None
        self._request_id = 0

    def _next_id(self) -> str:
        self._request_id += 1
        return str(self._request_id)

    async def connect(self) -> None:
        import aiohttp
        self._session = aiohttp.ClientSession(
            headers={"Content-Type": "application/json", **self._headers},
            timeout=aiohttp.ClientTimeout(total=self._timeout),
        )

    async def send_request(self, method: str, params: dict | None = None) -> dict:
        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        async with self._session.post(self._url, json=payload) as resp:
            result = await resp.json()
        if "error" in result:
            err = result["error"]
            raise McpError(err.get("code", 0), err.get("message", str(err)))
        return result.get("result", {})

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        async with self._session.post(self._url, json=payload) as resp:
            await resp.read()

    async def close(self) -> None:
        if self._session:
            await self._session.close()


def create_transport(config: dict) -> McpTransport:
    if "command" in config:
        return StdioTransport(
            command=config["command"],
            args=config.get("args"),
            env=config.get("env"),
        )
    if "url" in config:
        return HttpTransport(
            url=config["url"],
            headers=config.get("headers"),
            timeout=config.get("timeout", 120),
        )
    raise ValueError("MCP server config must have either 'command' or 'url'")
