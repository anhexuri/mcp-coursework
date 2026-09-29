"""端到端测试：通过 MCP HTTP 客户端调用 chat 工具。"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    url = "http://127.0.0.1:8765/mcp"
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("协商协议版本:", init.protocol_version)
            print("服务端:", init.server_info.name)

            tools = await session.list_tools()
            print("工具列表:", [t.name for t in tools.tools])

            result = await session.call_tool("chat", {"message": "用一句话介绍你自己"})
            print("chat 结果:", result.content[0].text if result.content else result)


if __name__ == "__main__":
    asyncio.run(main())
