"""MCP (Model Context Protocol) 客户端模块。

设计要点：
1. 以程序启动时的工作目录为项目根，读取其中的 .mcp.json 配置；
2. 支持 stdio 和 streamable_http 两种传输方式；
3. 启动时同步连接所有 MCP Server，list_tools 拿工具清单；
4. 工具命名统一用 "服务器名称__工具名" 的双下划线前缀，避免跨 Server 重名；
5. 某个 Server 连不上或报错时只输出错误日志，不影响其他 Server 和本地工具；
6. 用 asyncio.run() 把 MCP 异步接口包装成同步函数，与现有 TOOL_IMPL 风格一致。
7. 【关键】Streamable HTTP session 只在同一个 asyncio event loop 内有效，
   所以 sessions dict 存的是 (server_name, cfg)，每次 call_tool 都新建
   async 上下文重连一次（HTTP 短连接模式），避免跨 event loop 的 session 失效。
"""
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

# MCP Python SDK
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

# 程序启动时的工作目录即项目根（与 skills.PROJECT_ROOT 对齐）
PROJECT_ROOT = os.getcwd()
MCP_CONFIG_FILENAME = '.mcp.json'
# 服务器名与工具名的分隔符（双下划线，在合法工具名里极少出现）
TOOL_PREFIX_SEP = '__'


@dataclass
class RegisteredTool:
    """注册到 Agent 的 MCP 工具元数据"""
    server_name: str          # 配置里的 key
    original_name: str        # MCP Server 返回的原始工具名
    exposed_name: str         # 暴露给 LLM 的名称 = server_name__original_name
    description: str
    input_schema: dict        # JSON Schema


@dataclass
class MCPClientRegistry:
    """MCP Server 配置 + 工具注册中心。

    注意：sessions 存的不是 ClientSession，而是原始 server 配置 dict，
    因为 streamable_http 的 session 跨 event loop 会断。每次 call_tool 都重连。
    """
    # server_name → 原始 cfg dict（每次 call_tool 用它重连）
    sessions: Dict[str, dict] = field(default_factory=dict)
    # 暴露给 LLM 的 RegisteredTool
    tools: List[RegisteredTool] = field(default_factory=list)
    # exposed_name → (server_name, original_name) 反向映射
    name_map: Dict[str, tuple] = field(default_factory=dict)
    # 连不上的 Server 错误信息（启动时收集）
    errors: List[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.sessions)


# 全局单例（与 TOOL_IMPL / TOOLS 的静态注册风格一致）
REGISTRY = MCPClientRegistry()


# ---------- 配置加载 ----------

def load_mcp_config(root: str = None) -> dict:
    """读取项目根目录下的 .mcp.json，返回原始字典。不存在或格式错误返回空 dict。"""
    root = root or PROJECT_ROOT
    path = os.path.join(root, MCP_CONFIG_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 兼容顶层直接放 servers 或包在 mcpServers 里两种写法
        servers = data.get('mcpServers') or data.get('servers') or data
        if isinstance(servers, dict):
            return servers
        return {}
    except (json.JSONDecodeError, IOError) as e:
        print(f"[mcp] 读取 {path} 失败: {e}", file=sys.stderr)
        return {}


# ---------- 连接 + 工具发现 ----------

async def _discover_one(name: str, cfg: dict) -> Optional[tuple]:
    """连接单个 Server，list_tools。返回 (name, cfg, [Tool]) 或 None（失败）。"""
    stype = cfg.get('type', '').lower()
    try:
        if stype in ('streamable_http', 'http', 'sse'):
            url = cfg.get('url', '')
            if not url:
                raise ValueError("缺少 url")
            async with streamable_http_client(url=url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return name, cfg, result.tools
        elif stype in ('stdio', 'local'):
            cmd = cfg.get('command', '')
            args = cfg.get('args', [])
            if not cmd:
                raise ValueError("缺少 command")
            params = StdioServerParameters(command=cmd, args=args)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return name, cfg, result.tools
        else:
            raise ValueError(f"不支持的 type: {stype}（需 streamable_http 或 stdio）")
    except Exception as e:
        REGISTRY.errors.append(f"{name}: {e}")
        return None


async def _do_call(server_cfg: dict, original_name: str, arguments: dict) -> str:
    """单次 call_tool 内部实现——在同一个 async 上下文里连接 + 调用。"""
    stype = server_cfg.get('type', '').lower()
    async def _with_session(session):
        result = await session.call_tool(original_name, arguments=arguments or {})
        parts = []
        for item in getattr(result, 'content', []) or []:
            if hasattr(item, 'text') and item.text:
                parts.append(item.text)
            elif hasattr(item, 'data'):
                parts.append(f"[base64 image {len(item.data)} bytes]")
            else:
                parts.append(str(item))
        if parts:
            return "\n".join(parts)
        return json.dumps(getattr(result, 'model_dump', lambda: {})(),
                          ensure_ascii=False, default=str)

    if stype in ('streamable_http', 'http', 'sse'):
        url = server_cfg.get('url', '')
        async with streamable_http_client(url=url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await _with_session(session)
    elif stype in ('stdio', 'local'):
        params = StdioServerParameters(
            command=server_cfg.get('command', ''),
            args=server_cfg.get('args', []),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await _with_session(session)
    else:
        raise ValueError(f"未知 type: {stype}")


def init_mcp(root: str = None) -> None:
    """初始化 MCP：读配置 → 连接发现 → 注册工具（只存 cfg，不存 session）。"""
    if not _MCP_AVAILABLE:
        REGISTRY.errors.append("mcp Python SDK 未安装，请 pip install mcp")
        return
    servers = load_mcp_config(root)
    if not servers:
        return

    async def _discover_all():
        tasks = [_discover_one(n, c) for n, c in servers.items()]
        # return_exceptions=True：一个 Server 失败不影响其他
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                REGISTRY.errors.append(f"(gather) {res}")
                continue
            if res is None:
                continue
            name, cfg, tool_list = res
            REGISTRY.sessions[name] = cfg  # 只存 cfg
            for t in tool_list:
                schema = t.input_schema if isinstance(t.input_schema, dict) else {}
                exposed = f"{name}{TOOL_PREFIX_SEP}{t.name}"
                rt = RegisteredTool(
                    server_name=name,
                    original_name=t.name,
                    exposed_name=exposed,
                    description=t.description or "",
                    input_schema=schema,
                )
                REGISTRY.tools.append(rt)
                REGISTRY.name_map[exposed] = (name, t.name)

    asyncio.run(_discover_all())

    if REGISTRY.errors:
        for err in REGISTRY.errors:
            print(f"[mcp] {err}", file=sys.stderr)
    print(f"[mcp] 已发现 {len(REGISTRY.sessions)} 个 Server，注册 {len(REGISTRY.tools)} 个工具")


# ---------- 工具调用 ----------

def _call_mcp_tool(exposed_name: str, args: dict) -> str:
    """被 TOOL_IMPL 的动态 lambda 间接调用，每次重连一次（HTTP 短连接）。"""
    if exposed_name not in REGISTRY.name_map:
        return f"错误: 未知 MCP 工具 {exposed_name}"
    server_name, original_name = REGISTRY.name_map[exposed_name]
    cfg = REGISTRY.sessions.get(server_name)
    if cfg is None:
        return f"错误: MCP Server {server_name} 未注册"

    try:
        return asyncio.run(_do_call(cfg, original_name, args or {}))
    except Exception as e:
        return f"MCP Server {server_name} 调用 {original_name} 失败: {e}"


def shutdown_mcp() -> None:
    """不需要显式关闭：因为不持有持久 session，每次 call 都自建自毁。"""
    REGISTRY.sessions.clear()
    REGISTRY.tools.clear()
    REGISTRY.name_map.clear()


# ---------- TOOL_IMPL 动态注册 & TOOLS 追加 ----------

def get_mcp_tool_entries():
    """返回 list[(exposed_name, impl_callable, tool_schema_dict)] 供 TOOLS / TOOL_IMPL 注入。"""
    entries = []
    for rt in REGISTRY.tools:
        entries.append((
            rt.exposed_name,
            lambda args, _name=rt.exposed_name: _call_mcp_tool(_name, args),
            {
                "type": "function",
                "function": {
                    "name": rt.exposed_name,
                    "description": f"【MCP:{rt.server_name}】{rt.description}",
                    "parameters": rt.input_schema or {"type": "object", "properties": {}, "required": []},
                }
            }
        ))
    return entries


def get_server_status_list() -> list:
    """返回 [(server_name, status_str, [tool_name, ...]), ...] 列表，供 TUI 侧边栏显示。

    status_str: "connected" / "failed" / "not_configured"
    """
    result = []
    if not _MCP_AVAILABLE:
        return [("(mcp sdk not installed)", "failed", [])]
    if not REGISTRY.sessions:
        if REGISTRY.errors:
            return [("(所有 server 连接失败)", "failed", [])]
        return []  # 没配 .mcp.json

    # 先把 tool 按 server_name 分组
    tool_map: dict = {}
    for rt in REGISTRY.tools:
        tool_map.setdefault(rt.server_name, []).append(rt.exposed_name)

    for name in REGISTRY.sessions:
        tools = tool_map.get(name, [])
        if tools:
            result.append((name, "connected", tools))
        else:
            result.append((name, "connected (0 tools)", []))

    # 连不上的
    for err_line in REGISTRY.errors:
        # err_line 形如 "ServerName: ..."
        server_name = err_line.split(':', 1)[0]
        if server_name and server_name not in REGISTRY.sessions:
            result.append((server_name, "failed", []))

    return result

