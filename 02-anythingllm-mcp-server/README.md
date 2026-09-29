# AnythingLLM MCP Server (MVP)

通过 MCP（Model Context Protocol，协议版本 `2026-07-28`）以 **HTTP 传输（Streamable HTTP）** 暴露本机 AnythingLLM 的问答能力。

当前 MVP 仅提供 **一个工具** `chat`：向 AnythingLLM **第一个工作区** 提问，返回 AI 回答。

## 架构

- 传输：Streamable HTTP（非 stdio），端点 `http://127.0.0.1:8765/mcp`
- 协议：基于官方 `mcp` SDK 2.2.0，`LATEST_PROTOCOL_VERSION = 2026-07-28`
  - 客户端发送请求头 `MCP-Protocol-Version: 2026-07-28` 即走 **modern 无状态路径**（per-request 封装，无需 `initialize` 握手）
  - 同时向后兼容传统 `initialize` 握手路径
- 上游：AnythingLLM `POST /api/v1/workspace/{slug}/chat`，取 `textResponse` 字段返回

## 目录结构

```
McpSever/
├── server.py          # MCP 服务（单个 chat 工具）
├── .env               # 配置（API key、base URL、工作区 slug、端口）
├── requirements.txt   # 依赖
├── test_client.py     # 端到端测试客户端
├── .gitignore
└── README.md
```

## 前置条件

- Python 3.11+
- 本机已运行 AnythingLLM（默认 `http://localhost:3001`），并已创建至少一个工作区
- AnythingLLM 的 API Key（在 AnythingLLM 设置 → API Keys 中生成）

## 安装

```powershell
# 在项目根目录
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 配置

编辑 [.env](./.env)：

```env
ANYTHINGLLM_BASE_URL=http://localhost:3001
ANYTHINGLLM_API_KEY=你的AnythingLLM-API-Key
# 第一个工作区的 slug：调用 GET /api/v1/workspaces，取 workspaces[0].slug
ANYTHINGLLM_WORKSPACE_SLUG=62ed4385-e48e-45b8-bcc7-b6d20aeefe47
MCP_HOST=127.0.0.1
MCP_PORT=8765
```

> 获取工作区 slug：
> ```powershell
> curl.exe -s -H "Authorization: Bearer <你的API-Key>" http://localhost:3001/api/v1/workspaces
> ```

## 启动 / 停止 MCP 服务

### 启动

```powershell
# 前台运行（日志直接输出，Ctrl+C 停止）
.\.venv\Scripts\python.exe server.py
```

启动成功后可见：
```
INFO:     Uvicorn running on http://127.0.0.1:8765 (Press CTRL+C to quit)
```

### 后台运行（可选）

```powershell
Start-Process -WindowStyle Hidden -FilePath .\.venv\Scripts\python.exe -ArgumentList "server.py"
# 日志写入当前目录 mcp_server.log（见下方说明）
```

带日志重定向的后台启动：
```powershell
Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList "server.py" `
  -WindowStyle Hidden -RedirectStandardOutput mcp_server.log -RedirectStandardError mcp_server.err
```

### 停止

- 前台运行：在终端按 `Ctrl+C`。
- 后台运行：按端口查找并结束进程：
  ```powershell
  # 查找占用 8765 端口的进程
  Get-NetTCPConnection -LocalPort 8765 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }
  ```
  或直接：
  ```powershell
  Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*\.venv\*' } | Stop-Process -Force
  ```

### 自检

启动后运行端到端测试，确认 chat 工具可用：

```powershell
.\.venv\Scripts\python.exe test_client.py
```

预期输出包含 AI 回答，例如：
```
协商协议版本: 2025-11-25     # 传统握手路径；modern 路径使用 2026-07-28
服务端: AnythingLLM
工具列表: ['chat']
chat 结果: <AnythingLLM 返回的 AI 回答>
```

### 直接 curl 验证（2026-07-28 modern 路径）

```powershell
curl.exe -s -X POST -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "MCP-Protocol-Version: 2026-07-28" `
  -H "mcp-method: tools/call" -H "mcp-name: chat" `
  --data-binary '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"chat\",\"arguments\":{\"message\":\"你好\"},\"_meta\":{\"io.modelcontextprotocol/protocolVersion\":\"2026-07-28\",\"io.modelcontextprotocol/clientCapabilities\":{}}}}' `
  http://127.0.0.1:8765/mcp
```

## 配置为 Trae 项目级 MCP

> ⚠️ 出于安全考虑，`.trae/mcp.json` 不允许由 AI 助手直接写入，需**你手动创建**。

1. 在项目根目录创建 `.trae/mcp.json`，内容如下：

   ```json
   {
     "mcpServers": {
       "anythingllm": {
         "type": "http",
         "url": "http://127.0.0.1:8765/mcp"
       }
     }
   }
   ```

2. **先启动 MCP 服务**（HTTP 传输要求服务端已运行，Trae 不会自动拉起）：
   ```powershell
   .\.venv\Scripts\python.exe server.py
   ```

3. 在 Trae 中重新加载 MCP 服务列表（或重启 Trae）。之后对话中即可调用 `chat` 工具，由 AnythingLLM 第一个工作区作答。

> 也可在 Trae 的 `设置 → MCP` 界面通过“添加 MCP Server / HTTP”填入上述 URL 完成配置。

## 工具说明

| 工具 | 入参 | 说明 |
| --- | --- | --- |
| `chat` | `message: str` | 向 AnythingLLM 第一个工作区提问，返回 AI 文本回答 |

服务端固定使用 `sessionId="mcp-server"`，保留同一会话上下文（受工作区 `openAiHistory` 限制）。

## 故障排查

- **`Connection refused` / Trae 连不上**：确认服务已启动并监听 `127.0.0.1:8765`（`Get-NetTCPConnection -LocalPort 8765`）。
- **`401 Unauthorized` / 空 textResponse**：检查 `.env` 中 `ANYTHINGLLM_API_KEY` 与 `ANYTHINGLLM_WORKSPACE_SLUG` 是否正确。
- **端口冲突**：修改 `.env` 的 `MCP_PORT`，并同步更新 `.trae/mcp.json` 的 `url`。
