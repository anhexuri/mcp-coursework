"""AnythingLLM MCP Server.

通过 HTTP (Streamable HTTP) 暴露 AnythingLLM 的核心能力：
- list_workspaces / get_workspace  工作区查询
- chat                              与工作区对话
- query                             RAG 查询（只返回相关文档片段）
- system_info                       系统状态
"""

import json
import os

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()

BASE_URL = os.getenv("ANYTHINGLLM_BASE_URL", "http://localhost:3001").rstrip("/")
API_KEY = os.getenv("ANYTHINGLLM_API_KEY")
HOST = os.getenv("MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("MCP_PORT", "8765"))

mcp = MCPServer(
    "AnythingLLM",
    description="本机 AnythingLLM 网关：工作区管理、AI 对话、RAG 查询、系统状态",
)


def _headers() -> dict:
    if not API_KEY:
        raise ValueError("缺少环境变量 ANYTHINGLLM_API_KEY")
    return {"Authorization": f"Bearer {API_KEY}"}


async def _get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{BASE_URL}{path}", headers=_headers())
        r.raise_for_status()
        return r.json()


async def _post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post(f"{BASE_URL}{path}", headers=_headers(), json=payload)
        r.raise_for_status()
        return r.json()


async def _first_workspace_slug() -> str:
    data = await _get("/api/v1/workspaces")
    ws_list = data.get("workspaces", [])
    if not ws_list:
        raise RuntimeError("AnythingLLM 中没有任何工作区")
    return ws_list[0]["slug"]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_workspaces() -> str:
    """列出 AnythingLLM 中所有工作区及其基本信息（名称、slug、向量标签）。"""
    data = await _get("/api/v1/workspaces")
    return json.dumps(data.get("workspaces", []), ensure_ascii=False, indent=2)


@mcp.tool()
async def get_workspace(slug: str = "") -> str:
    """查询单个工作区详情；不传 slug 时返回第一个工作区。

    Args:
        slug: 工作区的唯一标识，可从 list_workspaces 获得。留空默认第一个。
    """
    if not slug:
        slug = await _first_workspace_slug()
    data = await _get(f"/api/v1/workspace/{slug}")
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def chat(message: str, slug: str = "", mode: str = "chat") -> str:
    """向 AnythingLLM 工作区提问，返回 AI 的回答。

    Args:
        message: 要提问的问题。
        slug: 目标工作区 slug，留空默认使用第一个工作区。
        mode: chat（对话）或 query（只查不答），默认 chat。
    """
    if not slug:
        slug = await _first_workspace_slug()
    payload = {"message": message, "mode": mode, "sessionId": "mcp-server"}
    data = await _post(f"/api/v1/workspace/{slug}/chat", payload)
    if data.get("error"):
        raise RuntimeError(data["error"])
    text = data.get("textResponse", "")
    sources = data.get("sources") or []
    if sources:
        src_lines = [f"- {s.get('title','?')}" for s in sources]
        text += "\n\n相关来源:\n" + "\n".join(src_lines)
    return text


@mcp.tool()
async def query(message: str, slug: str = "") -> str:
    """纯 RAG 查询：只返回与问题最相关的文档片段，不经过 LLM 生成。

    Args:
        message: 要查询的问题。
        slug: 目标工作区 slug，留空默认使用第一个工作区。
    """
    if not slug:
        slug = await _first_workspace_slug()
    # 复用 chat 接口但 mode=query，让模型只返回检索结果
    payload = {"message": message, "mode": "query", "sessionId": "mcp-query"}
    data = await _post(f"/api/v1/workspace/{slug}/chat", payload)
    if data.get("error"):
        raise RuntimeError(data["error"])
    text = data.get("textResponse", "")
    sources = data.get("sources") or []
    if sources:
        text += "\n\n📎 相关文档:\n"
        for s in sources:
            text += f"• {s.get('title','?')} (相似度 {s.get('score',0):.2f})\n"
    return text


@mcp.tool()
async def system_info() -> str:
    """获取 AnythingLLM 系统设置、已索引向量数量等状态信息。"""
    sys_data = await _get("/api/v1/system")
    embed_data = await _get("/api/v1/embed")
    return json.dumps({
        "system": sys_data,
        "embeds": embed_data,
    }, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=HOST, port=PORT)
