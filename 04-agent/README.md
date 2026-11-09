# AgentEvanescia —— 终端 AI Agent（Python · Textual · MCP）

课程四：在终端里运行的通用 AI Agent。基于 OpenAI 兼容接口 + Textual TUI，
支持**技能动态加载**、**MCP 工具接入**、**上下文压缩归档**与会话持久化。

## 功能特性

| 模块 | 说明 |
| --- | --- |
| 终端 TUI | Textual 实现的三栏界面：左侧技能/MCP 侧栏、中间对话流、底部上下文用量进度条 |
| 技能系统 | 启动时扫描 `.agents/skills/**/SKILL.md`，只读 frontmatter；正文由 `loadSkill` 按需加载，不占常驻上下文 |
| MCP Client | 读取项目根 `.mcp.json`，支持 `streamable_http` 与 `stdio` 两种传输，工具名以 `ServerName__tool` 暴露 |
| 上下文压缩 | `/compact` 把历史归档成 `.agents/context/YYYYMMDD-HHMMSS.jsonl`，再由模型生成摘要接续对话 |
| 上下文回溯 | `recallContext` 工具在归档中做全文检索，摘要丢失的细节可随时找回 |
| 会话持久化 | `/save` `/resume` `/sessions`，会话存于 `.agents/sessions/` |
| 本地工具 | 读写文件、目录管理、执行 CLI、联网搜索与网页抓取 |
| 安全边界 | 只读模式（Ctrl+R 切换）；Office 二进制后缀禁止用纯文本工具写入 |

## 目录结构

```
04-agent/
├── main.py                  # 入口：UTF-8 修复 → 生成 config.ini → 启动 TUI
├── requirements.txt
├── run.bat                  # Windows 一键启动
├── xagent/
│   ├── core/
│   │   ├── llm.py           # AgentCore：对话循环、工具调用、上下文压缩
│   │   ├── mcp.py           # MCP 客户端（streamable_http / stdio）
│   │   ├── tools.py         # 工具 schema 与实现注册表
│   │   ├── skills.py        # 技能发现与加载
│   │   ├── context.py       # 上下文归档与全文检索
│   │   ├── session.py       # 会话持久化
│   │   ├── fileops.py       # 文件操作（含 Office 后缀拦截）
│   │   ├── cliops.py        # 本地 CLI 调用
│   │   ├── webops.py        # 联网搜索 / 网页抓取
│   │   └── config.py        # config.ini 读取与模板自动生成
│   └── tui/app.py           # Textual 界面
└── README.md
```

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 配置

首次启动若项目根目录没有 `config.ini`，程序会**自动生成带注释的模板**并提示填写 API Key。

```ini
[llm]
api_key = sk-REPLACE_ME_WITH_REAL_API_KEY
base_url = https://api.deepseek.com/v1/
model = deepseek-chat
# context_window = 128000

[agent]
read_only = true
max_tool_rounds = 10
usage_warn_ratio = 0.8
compact_target_tokens = 5000
load_agents_md = true
sessions_dir = .agents\sessions
mcp_config_path = .mcp.json

[search]
api_key =
base_url = https://qianfan.baidubce.com/v2/ai_search
```

- `config.ini` 已加入 `.gitignore`，不会提交到仓库。
- 项目根有 `AGENTS.md` 时，内容会在会话启动时一次性注入 System Prompt。

## 接入 MCP Server

在项目根创建 `.mcp.json`：

```json
{
  "mcpServers": {
    "anythingllm": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8765/mcp"
    },
    "pet-hospital": {
      "type": "stdio",
      "command": "python",
      "args": ["../03-pet-hospital-mcp/main.py"]
    }
  }
}
```

启动后侧栏会列出已连接的 Server 与工具数量；连接失败不影响 TUI 启动，仅标记为 `✗`。

## 使用

```powershell
# 方式一
python main.py

# 方式二（Windows 双击）
run.bat
```

### 斜杠命令

| 命令 | 作用 |
| --- | --- |
| `/help` | 查看全部命令与快捷键 |
| `/compact` | 压缩上下文并归档原始历史 |
| `/new` | 开始新会话 |
| `/save` `/resume` `/sessions` | 保存 / 恢复 / 列出会话 |
| `/reset` | 重置当前对话 |
| `/archives` | 列出上下文归档 |
| `/mcp` | 查看 MCP Server 与工具 |
| `/skills` | 查看已加载技能 |
| `/quit` | 退出 |

### 快捷键

`Ctrl+Q` 退出 · `Ctrl+R` 只读/读写切换 · `Ctrl+Shift+C` 压缩上下文 · `Ctrl+Y` 复制上条回复 · `Ctrl+S` 保存会话 · `Ctrl+L` 清屏

## 技能（Skill）

技能是"按需加载的知识包"，目录结构：

```
.agents/skills/<skill-name>/SKILL.md
```

`SKILL.md` 需以 YAML frontmatter 开头：

```markdown
---
name: office-cli
description: 何时使用该技能的一句话说明
---

（正文：具体步骤、命令、禁忌）
```

启动时只解析 `name` 与 `description`（很省 token），真正需要时模型调用 `loadSkill(name)` 读取正文，或 `loadSkill(name, filename)` 读取技能目录下的附加文件（`references/`、`scripts/`）。

## 上下文压缩与回溯

- 达到 `context_window` 的 `usage_warn_ratio`（默认 80%）时，界面会警告并阻止普通输入，需先 `/compact`。
- `/compact` 会把原始消息写入 `.agents/context/`，再请模型生成约 `compact_target_tokens` 的摘要继续对话。
- 摘要末尾附带归档编号；细节缺失时用 `recallContext(text="关键词")` 到归档里全文检索。

## 说明

- 默认只读模式：模型看不到 `createFile / editFile / mkdir / rmdir / deleteFile / rename`。
- `.docx / .xlsx / .pptx` 等二进制文档禁止用文本工具写入，需调用专门的 CLI（如 `officecli`）生成。
