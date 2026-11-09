"""LLM 编排层：多轮工具调用循环 + 上下文压缩 + Token 追踪。

通过事件回调（on_event）向 UI 上报过程，core 不依赖任何具体界面。
"""
import json
import os

from openai import OpenAI

from . import context as context_mod
from . import mcp as mcp_mod
from .config import load_agent_config, load_config
from .skills import build_skills_prompt, get_skills
from .tools import TOOLS, TOOL_IMPL, READONLY_TOOL_NAMES, register_mcp_tools

COMPACT_SYSTEM_PROMPT_TEMPLATE = (
    "你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，"
    "需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。\n\n"
    "请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，"
    "并生成一份约 {target} Tokens 的 Markdown 摘要。\n\n"
    "摘要应重点保留以下内容：\n"
    "1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？\n"
    "2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？\n"
    "3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？\n"
    "4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。\n"
    "5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。\n"
    "6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。\n\n"
    "请遵守以下要求：\n"
    "- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。\n"
    "- 对已经验证的事实与尚未验证的推测作出明确区分。\n"
    "- 不要将计划完成的任务描述为已经完成。\n"
    "- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。\n"
    "- 对失败的尝试，只保留有助于避免重复错误的信息。\n"
    "- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。\n"
    "- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，"
    "后续可以通过 `recallContext` 工具重新检索。\n"
    "- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。\n\n"
    "**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"
)

# 双保险：告诉 LLM 什么时候该用工具，什么时候直接回答
SYSTEM_PROMPT = (
    "你是 AgentEvanescia，具备文件操作、技能加载、MCP 工具调用能力。"
    "\n\n【工具选择铁律】"
    "\n1. 已有 MCP 工具或 Skill 能回答的问题，不要用 searchWeb / fetchWeb 联网搜索。"
    "MCP 工具返回的数据更准确、更可控（不会返回过时的网页内容）。"
    "\n2. 用 MCP / Skill 拿到结果后，直接总结给用户，不要反复联网核实。"
    "\n3. searchWeb / fetchWeb 只在本地工具和 MCP 都无法覆盖时才用。"
    "\n\n【工具调用纪律】"
    "\n- 每一轮尽量一次性把能拿到的信息都拿到，然后输出最终回答，不要反复调同一个问题。"
    "\n- 如果某工具返回的结果已经够用，直接总结，不要再调第二个工具验证。"
    "\n- 只有当用户明确要求创建/编辑/删除/移动文件或目录时，才使用写入类工具。"
    "\n- 对于纯问题、闲聊、知识查询，直接用文本回答。"
    "\n- 如果压缩摘要缺少某些历史细节，请用 recallContext 工具检索原始归档，不要让用户重复描述。"
)


class AgentCore:
    def __init__(self, config=None, agent_cfg=None):
        config = config or load_config()
        agent_cfg = agent_cfg or load_agent_config()
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.model = config.model
        self.readonly = config.read_only
        self.context_window = config.context_window
        self.messages = []

        # 从 agent config 读运行参数（之前是模块级硬编码常量）
        self.max_tool_rounds = agent_cfg.max_tool_rounds
        self.usage_warn_ratio = agent_cfg.usage_warn_ratio
        self.compact_target_tokens = agent_cfg.compact_target_tokens
        self._agent_cfg = agent_cfg

        # 上一次 API 返回的 usage（优先信任）
        self._last_usage = None

        # 初始化阶段发现技能：只加载 name / description，正文由 loadSkill 按需读取
        self.skills = get_skills()
        # 初始化 MCP：读 .mcp.json → 连接所有 Server → 动态追加工具
        # 注意：MCP SDK 内部的 TaskGroup 异常可能往上冒，包一层 try 不让它阻塞 AgentCore 启动
        try:
            mcp_mod.init_mcp()
        except Exception as e:
            print(f"[mcp] init_mcp 顶层异常（已忽略）：{e}")
            # 初始化失败时 REGISTRY.errors 可能还没收集到，补一条
            if not mcp_mod.REGISTRY.errors:
                mcp_mod.REGISTRY.errors.append(f"(init_mcp) {e}")
        mcp_entries = mcp_mod.get_mcp_tool_entries()
        if mcp_entries:
            register_mcp_tools(mcp_entries)
            # 把 MCP 工具移到工具列表最前面，让 LLM 优先看到
            mcp_names = {e[0] for e in mcp_entries}
            mcp_tools = [t for t in TOOLS if t['function']['name'] in mcp_names]
            local_tools = [t for t in TOOLS if t['function']['name'] not in mcp_names]
            TOOLS.clear()
            TOOLS.extend(mcp_tools)
            TOOLS.extend(local_tools)
        self.mcp_registry = mcp_mod.REGISTRY
        self.system_prompt = SYSTEM_PROMPT
        skills_prompt = build_skills_prompt(self.skills)
        if skills_prompt:
            self.system_prompt = f"{SYSTEM_PROMPT}\n\n{skills_prompt}"
        if mcp_entries:
            self.system_prompt = (
                f"{self.system_prompt}\n\n"
                "以下工具来自 MCP Server，能直接回答对应领域问题，优先使用：\n"
                + "\n".join(f"- {e[0]}: {e[2]['function']['description'][:100]}" for e in mcp_entries)
                + "\n\n如果 MCP 工具能覆盖用户问题，就用 MCP，不要再 searchWeb。"
            )

        # 检查 AGENTS.md（一次注入，加进 system_prompt，后续每轮复用）
        self._agents_md_content = None
        if agent_cfg.load_agents_md:
            md_path = os.path.join(os.getcwd(), 'AGENTS.md')
            if os.path.isfile(md_path):
                try:
                    with open(md_path, 'r', encoding='utf-8') as f:
                        self._agents_md_content = f.read().strip()
                    self.system_prompt = (
                        f"{self.system_prompt}\n\n"
                        "---\n\n**项目自定义指令（AGENTS.md）**\n\n"
                        f"{self._agents_md_content}\n"
                    )
                except Exception as e:
                    # 读取失败不阻塞启动，只是跳过
                    print(f"[agent] 读取 AGENTS.md 失败：{e}")

    # ---------- 上下文容量查询 ----------

    @property
    def available_tools(self):
        """根据当前模式过滤出对 LLM 可见的工具列表（保持 MCP 工具在最前）"""
        if self.readonly:
            return [t for t in TOOLS if t['function']['name'] in READONLY_TOOL_NAMES]
        return list(TOOLS)

    @property
    def current_tokens(self) -> int:
        """估算当前（system + history）总 tokens。"""
        sys_tok = context_mod.estimate_tokens(self.system_prompt)
        hist_tok = context_mod.count_messages_tokens(self.messages)
        return sys_tok + hist_tok

    @property
    def usage_ratio(self) -> float:
        return self.current_tokens / self.context_window

    @property
    def needs_compact(self) -> bool:
        return self.usage_ratio >= self.usage_warn_ratio

    # ---------- MCP 状态（给 TUI 侧边栏看） ----------

    @property
    def mcp_server_list(self) -> list:
        """返回 [(server_name, status, [tool_name, ...]), ...] 列表。"""
        return mcp_mod.get_server_status_list()

    @property
    def skills_list(self) -> list:
        """返回 [(name, description), ...]。"""
        return [(s.name, s.description) for s in self.skills]

    @property
    def window_is_default(self) -> bool:
        """用户没在 config.ini 显式配置 context_window，用的默认值。"""
        try:
            cfg = load_config()
            return cfg.context_window == 128000
        except Exception:
            return True

    # ---------- 核心 run ----------

    def reset(self):
        """清空对话历史"""
        self.messages = []
        self._last_usage = None

    def run(self, user_input: str, on_event) -> str:
        """处理一轮用户输入，可能触发多轮工具调用，直到 AI 给出最终回答。

        若上下文已达阈值，返回特殊占位字符串，由 UI 层决定如何提示用户 compact。
        """
        # 阈值检查：超过 80% 阻塞普通输入，只允许 /compact 命令
        if self.needs_compact and not user_input.strip().startswith('/compact'):
            msg = (
                f"上下文已使用 {self.usage_ratio*100:.0f}% "
                f"（{self.current_tokens}/{self.context_window} tokens），"
                f"请执行 `/compact` 压缩后再继续对话。"
            )
            on_event({"type": "assistant", "content": msg})
            return msg

        self.messages.append({"role": "user", "content": user_input})
        tool_rounds = 0

        while True:
            tool_rounds += 1

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{'role': 'system', 'content': self.system_prompt}, *self.messages],
                tools=self.available_tools
            )
            # 记录 usage
            if getattr(response, 'usage', None):
                u = response.usage
                self._last_usage = {
                    'prompt': getattr(u, 'prompt_tokens', None),
                    'completion': getattr(u, 'completion_tokens', None),
                    'total': getattr(u, 'total_tokens', None),
                }
            msg = response.choices[0].message

            if msg.tool_calls:
                # 检查是否达到上限
                if tool_rounds > self.max_tool_rounds:
                    forced_note = (
                        f"\n\n【已达最大工具调用轮次（{self.max_tool_rounds} 次），"
                        f"强制停止。请基于以上工具结果直接回答用户，不要再调工具。】"
                    )
                    self.messages.append({
                        "role": "user",
                        "content": forced_note
                    })
                    try:
                        final = self.client.chat.completions.create(
                            model=self.model,
                            messages=[{'role': 'system', 'content': self.system_prompt}, *self.messages]
                        )
                        content = final.choices[0].message.content or forced_note
                    except Exception as e:
                        content = f"已达最大工具调用轮次 {MAX_TOOL_ROUNDS}，请手动查看以上工具结果。（API 错误: {e}）"
                    self.messages.append({"role": "assistant", "content": content})
                    on_event({"type": "assistant", "content": content})
                    return content

                # 记录 AI 发起的工具调用
                self.messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls]
                })
                # 执行工具并把结果回传给 AI
                for tool_call in msg.tool_calls:
                    try:
                        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                        name = tool_call.function.name
                        impl = TOOL_IMPL.get(name) or TOOL_IMPL.get(name.lower())
                        result = impl(args) if impl else f"未知工具: {name}"
                    except Exception as e:
                        result = f"工具执行出错: {e}"
                    on_event({"type": "tool_call", "name": tool_call.function.name, "result": result})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })
                continue

            self.messages.append({"role": "assistant", "content": msg.content})
            on_event({"type": "assistant", "content": msg.content})
            return msg.content

    # ---------- 上下文压缩 ----------

    def compact(self, on_event) -> str:
        """执行一次完整的上下文压缩：保存原始归档 → LLM 生成摘要 → 替换 messages。

        on_event 会收到：
          {"type": "info", "content": "..."}    进度提示
          {"type": "tool_call", ...}            （如果内部有工具调用——压缩本身不会，避免误解所以不发）
          {"type": "assistant", "content": "..."} 最终完成报告
        """
        on_event({"type": "info", "content": "开始压缩上下文..."})

        # 1. 保存原始归档
        try:
            archive_id = context_mod.save_archive(self.messages)
        except Exception as e:
            err = f"归档失败：{e}。原上下文未改动，可重试。"
            on_event({"type": "assistant", "content": err})
            return err
        on_event({"type": "info",
                  "content": f"原始上下文已保存到 .agents\\context\\{archive_id}.jsonl（{len(self.messages)} 条消息）"})

        # 2. 构造压缩请求——把当前 messages 全部送给 LLM
        compact_system = COMPACT_SYSTEM_PROMPT_TEMPLATE.format(target=self.compact_target_tokens)
        compact_messages = [
            {"role": "system", "content": compact_system},
            {"role": "user", "content": (
                "请压缩以下历史对话。输出 Markdown 摘要，保留关键决策和技术细节。\n\n"
                "--- 开始 ---\n"
                + self._serialize_messages_for_compact()
                + "\n--- 结束 ---"
            )}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=compact_messages,
            )
            summary = response.choices[0].message.content or "(压缩失败，返回为空)"
            if getattr(response, 'usage', None):
                self._last_usage = {
                    'prompt': getattr(response.usage, 'prompt_tokens', None),
                    'completion': getattr(response.usage, 'completion_tokens', None),
                    'total': getattr(response.usage, 'total_tokens', None),
                }
        except Exception as e:
            err = f"调用 LLM 压缩失败：{e}。原上下文未改动，可重试。"
            on_event({"type": "assistant", "content": err})
            return err

        # 3. 替换 messages：归档说明 + 摘要，不保留 tail（避免 tool/tool_calls 配对破坏）
        archive_note = (
            f"\n\n---\n\n"
            f"> 此前上下文已于 {_now_iso()} 完成压缩，"
            f"原始上下文保存在编号为 `{archive_id}` 的归档文件中。"
            f"如需查找历史信息，请使用 `recallContext` 工具（参数 `id={archive_id}` 可限定该归档）。"
        )

        self.messages = [
            {"role": "user", "content": "（上下文已压缩，以下为历史摘要，请基于摘要继续与用户对话。）"},
            {"role": "assistant", "content": summary + archive_note},
        ]

        # 4. 报告
        new_tok = self.current_tokens
        ratio = new_tok / self.context_window * 100
        ok = (
            f"✓ 压缩完成。\n"
            f"  - 归档编号：`{archive_id}`\n"
            f"  - 原消息数：{14}（实际条数见归档）→ 压缩为 2 条（占位 + 摘要）\n"
            f"  - 新估算 tokens：~{new_tok} / {self.context_window}（{ratio:.1f}%）\n"
            f"  - 使用 `recallContext(id=\"{archive_id}\", text=\"...\")` 检索历史"
        )
        on_event({"type": "assistant", "content": ok})
        return ok

    def _serialize_messages_for_compact(self) -> str:
        """把 messages 扁平化成可读文本给压缩用。"""
        lines = []
        for i, m in enumerate(self.messages, 1):
            role = m.get('role', '?')
            lines.append(f"### [{i}] {role.upper()}")
            # content
            c = m.get('content')
            if c:
                if isinstance(c, list):
                    for cc in c:
                        if isinstance(cc, dict) and cc.get('type') == 'text':
                            lines.append(cc.get('text', ''))
                else:
                    lines.append(str(c))
            # tool_calls
            for tc in m.get('tool_calls', []) or []:
                fn = tc.get('function', {})
                lines.append(f"[tool_call] {fn.get('name')}(args={fn.get('arguments','')})")
            # tool role
            if role == 'tool':
                lines.append(f"[tool_call_id={m.get('tool_call_id')}]")
            lines.append("")
        return "\n".join(lines)


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
