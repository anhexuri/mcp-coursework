# MCP / AnythingLLM / Agent 课程作业合集

四次课程的实践项目，围绕 **AnythingLLM 知识库**、**MCP（Model Context Protocol）** 与
**AI Agent** 展开，从网页调用、MCP 服务开发、Go 后端项目到自主 Agent，层层递进。

## 项目一览

| # | 项目 | 技术栈 | 简介 |
| --- | --- | --- | --- |
| 1 | [anythingllm-web](./01-anythingllm-web) | 原生 HTML / CSS / JavaScript | 单文件网页工作台：选择工作区对话、上传文档并自动向量化 |
| 2 | [anythingllm-mcp-server](./02-anythingllm-mcp-server) | Python · MCP SDK · httpx | 通过 MCP (Streamable HTTP) 把 AnythingLLM 封装成 AI 可调用的工具集 |
| 3 | [pet-hospital-mcp](./03-pet-hospital-mcp) | Go 标准库 · 自研存储引擎 | 宠物医院管理系统：网页 + REST API（查询/新增/删除/导出/统计），零第三方依赖 |
| 4 | [agent](./04-agent) | Python · Textual · MCP SDK | 终端 AI Agent：技能动态加载、MCP 接入、上下文压缩归档与会话持久化 |

## 目录结构

```
mcp-coursework
├── 01-anythingllm-web/        # 课程一：AnythingLLM 网页工作台
│   ├── index.html
│   └── README.md
├── 02-anythingllm-mcp-server/ # 课程二：AnythingLLM MCP 服务（Python）
│   ├── server.py
│   ├── test_client.py
│   ├── requirements.txt
│   └── README.md
├── 03-pet-hospital-mcp/       # 课程三：宠物医院 REST API（Go）
│   ├── main.go
│   ├── internal/
│   ├── Makefile
│   └── README.md
└── 04-agent/                  # 课程四：终端 AI Agent（Python）
    ├── main.py
    ├── xagent/
    ├── requirements.txt
    └── README.md
```

## 安全说明

- **禁止提交密钥**：课程一网页原本把 API Key 硬编码在页面里，公开到 GitHub 前已改为首次使用时输入、仅存本机浏览器；课程二的 `.env`（含 API Key）与 Python 虚拟环境 `.venv/` 均已通过 `.gitignore` 排除。
- 课程三的运行时数据库 `data/*.db`、编译产物 `dist/` 不纳入版本控制，首次运行自动生成。
- 课程四的 `config.ini`（含 LLM / 搜索 API Key）、`.agents/sessions`、`.agents/context` 与打包产物同样不纳入版本控制。

## 快速索引

- 课程一：[01-anythingllm-web/README.md](./01-anythingllm-web/README.md)
- 课程二：[02-anythingllm-mcp-server/README.md](./02-anythingllm-mcp-server/README.md)
- 课程三：[03-pet-hospital-mcp/README.md](./03-pet-hospital-mcp/README.md)
- 课程四：[04-agent/README.md](./04-agent/README.md)
