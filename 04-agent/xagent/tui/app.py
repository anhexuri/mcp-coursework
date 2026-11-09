"""基于 Textual 的 TUI 界面。

core 的工具调用循环是阻塞式的，因此放到后台线程 worker 中运行，
通过 call_from_thread 把事件安全地回传到 UI 线程渲染。
未来可在 xagent 下新增 web/、desktop/、mobile/ 等平级界面目录。
"""
import os

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Header, LoadingIndicator, Markdown, Static, TextArea

from ..core.llm import AgentCore
from ..core import session as session_mod


class InputArea(TextArea):
    """多行输入框：Enter 发送，Shift+Enter 换行。

    TextArea 默认 Enter 插入换行，这里在 widget 层拦截，
    阻止默认行为后向父级 App 发送 Submit 消息。
    """

    class Submit(Message):
        """Enter/Ctrl+Enter 触发的提交消息"""
        def __init__(self, text: str):
            super().__init__()
            self.text = text

    def on_key(self, event) -> None:
        key = event.key
        shift = getattr(event, 'shift', False)
        if key in ("enter", "ctrl+enter") and not shift:
            event.stop()
            self.post_message(self.Submit(self.text))


# ---------- 斜杠命令清单（给 /help 和补全面板用） ----------

SLASH_COMMANDS = [
    ("/compact",       "压缩上下文（保存原始归档 → LLM 生成摘要）"),
    ("/new",           "新建会话（自动保存当前会话到 sessions）"),
    ("/resume",        "恢复历史会话（交互式选择）"),
    ("/save",          "手动保存当前会话到 sessions"),
    ("/reset",         "清空当前对话（不归档、不保存）"),
    ("/archives",      "列出已保存的上下文压缩归档"),
    ("/sessions",      "列出所有已保存的会话"),
    ("/mcp",           "显示 MCP Server 连接状态和工具"),
    ("/skills",        "显示当前项目已注册的 Skills"),
    ("/help",          "显示斜杠命令帮助"),
    ("/quit",          "保存会话并退出（等同 Ctrl+Q）"),
]


class FileOpsTUI(App):
    """AgentEvanescia 终端界面"""

    TITLE = "AgentEvanescia"
    THEME = "textual-dark"  # Textual 内置深色主题，Windows 终端兼容最稳
    BINDINGS = [("ctrl+l", "clear", "清屏"),
                ("ctrl+q", "quit", "退出"),
                ("ctrl+r", "toggle_readonly", "切换只读模式"),
                ("ctrl+shift+c", "compact", "压缩上下文"),
                ("ctrl+y", "copy_last", "复制上条 AI 回复到剪贴板"),
                ("ctrl+s", "save_session", "保存当前会话")]
    CSS = """
    Screen { layout: vertical; }
    Header { height: 1; }

    /* 中间主区：横向排列 sidebar + main-area */
    #main-row { layout: horizontal; height: 1fr; }

    /* 左侧栏 */
    #sidebar {
        width: 30; height: 1fr;
        background: $surface;
        border-right: round $primary-background;
        padding: 0 1;
        overflow-y: auto;
    }
    #sidebar-header {
        color: $primary; text-style: bold;
        border-bottom: thick $primary-background;
        padding: 1 0 0 0;
    }
    #skills-title, #mcp-title {
        color: $text-muted; text-style: bold; margin-top: 1;
    }

    /* 右侧主区 */
    /* 右侧主区：Vertical 容器（不带滚动），chat 自己是 VerticalScroll */
    #main-area { width: 1fr; height: 1fr; }
    #chat { height: 1fr; padding: 1 2; }

    .msg-user {
        background: $surface; border-left: thick $success;
        padding: 0 1; width: 1fr;
    }
    .msg-ai {
        background: $panel; border-left: thick $primary;
        padding: 0 1; width: 1fr;
    }
    .msg-tool {
        color: $warning; background: $surface;
        border-left: thick $warning; padding: 0 1; width: 1fr;
        text-style: dim;
    }
    .msg-system { color: $text-muted; text-style: italic; margin-bottom: 1; }

    #input-row { height: auto; align: center middle; }
    #spinner { width: 3; height: 3; visibility: hidden; }
    #spinner.busy { visibility: visible; }
    #textarea {
        height: 4; border: round $primary-background;
        padding: 0 1;
    }
    #textarea:focus { border: round $primary; }

    #footer-bar {
        height: 1; background: $surface; color: $text-muted;
        padding: 0 2; align: left middle;
    }
    """

    def __init__(self, agent: AgentCore = None):
        super().__init__()
        self.agent = agent or AgentCore()
        self._busy = False

    # ---------- 布局 ----------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-row"):
            with VerticalScroll(id="sidebar"):
                yield Static("AgentEvanescia", id="sidebar-header")
                yield Static("Skills", id="skills-title")
                yield Static("MCP Servers", id="mcp-title")
            # main-area 用 Vertical（不带滚动），只有 chat 自己滚
            with Vertical(id="main-area"):
                with VerticalScroll(id="chat"):
                    yield Static(
                        f"AgentEvanescia 已就绪。"
                        f"项目根: [{os.getcwd()}]. "
                        f"\n（Enter 发送 / Shift+Enter 换行）\n"
                        f"斜杠命令: /help",
                        classes="msg-system", markup=False
                    )
                with Horizontal(id="input-row"):
                    yield LoadingIndicator(id="spinner", name="dots")
                    yield InputArea(placeholder="输入指令，Enter 发送，Shift+Enter 换行（/help 查看命令）", id="textarea")
        yield Static("", id="footer-bar", markup=False)

    def on_mount(self) -> None:
        self.theme = self.THEME
        self._update_title_mode()
        self._refresh_sidebar()
        self.query_one("#textarea", TextArea).focus()

    # ---------- 侧边栏刷新 ----------

    def _refresh_sidebar(self) -> None:
        """重绘左侧 Skills + MCP 区域。"""
        sidebar = self.query_one("#sidebar")
        # 清掉上一次动态 mount 的内容（保留 header + 两个 title）
        for child in list(sidebar.children):
            cid = getattr(child, 'id', '') or ''
            if cid in ('sidebar-header', 'skills-title', 'mcp-title'):
                continue
            # 其余动态 widget 全部移除
            child.remove()

        skills_title = sidebar.query_one('#skills-title')
        mcp_title = sidebar.query_one('#mcp-title')

        # Skills：依次 mount 到 skills_title 之后
        anchor = skills_title
        for w in self._render_skills():
            sidebar.mount(w, after=anchor)
            anchor = w

        # MCP：依次 mount 到 mcp_title 之后
        anchor = mcp_title
        for w in self._render_mcp():
            sidebar.mount(w, after=anchor)
            anchor = w

    def _render_skills(self) -> list:
        """返回 Static widget 列表（id=None，避免重复）。"""
        widgets = []
        skills = self.agent.skills_list
        if not skills:
            widgets.append(Static("  （无 Skills）"))
            return widgets
        for name, desc in skills:
            widgets.append(Static(f"  • {name}"))
            widgets.append(Static(f"    {desc[:45]}{'…' if len(desc) > 45 else ''}"))
        return widgets

    def _render_mcp(self) -> list:
        widgets = []
        servers = self.agent.mcp_server_list
        if not servers:
            widgets.append(Static("  （未配置 .mcp.json）"))
            return widgets
        for name, status, tools in servers:
            if status == 'connected':
                widgets.append(Static(f"  ✓ {name} ({len(tools)})"))
                shown = tools[:10]
                for t in shown:
                    short = t.split('__', 1)[1] if '__' in t else t
                    widgets.append(Static(f"    ↳ {short}"))
                if len(tools) > 10:
                    widgets.append(Static(f"    …+{len(tools)-10} more"))
            elif status == 'failed':
                widgets.append(Static(f"  ✗ {name} (失败)"))
            else:
                widgets.append(Static(f"  ? {name}"))
        return widgets

    # ---------- Footer Bar ----------

    def _update_title_mode(self) -> None:
        """更新 Footer Bar：模式 + ctx 用量 + 归档数 + 压缩警告。"""
        self.title = "AgentEvanescia" + (" [只读]" if self.agent.readonly else "")

        try:
            cur = self.agent.current_tokens
            win = self.agent.context_window
            default_tag = "（默认）" if self.agent.window_is_default else ""
            pct = cur / win * 100

            if pct >= 90:
                bar_color, warn = "red", "  ⚠️ 请尽快 /compact"
            elif pct >= 80:
                bar_color, warn = "yellow", "  ⚠️ 建议 /compact"
            else:
                bar_color, warn = "green", ""

            filled = min(5, max(0, int(pct / 20 + 0.5)))
            bar_chars = "█" * filled + "░" * (5 - filled)
            bar_rich = f"[{bar_color}]{bar_chars}[/] [{bar_color}]{pct:.0f}%[/]"

            mode = "[只读]" if self.agent.readonly else "[读写]"
            ctx = f"ctx: {cur//1024}k/{win//1024}k{default_tag}"

            try:
                from ..core import context as ctx_mod
                arcs = ctx_mod.list_archives()
                arc = f"📁 {len(arcs)} 归档"
            except Exception:
                arc = "📁 -"

            try:
                sessions = session_mod.list_sessions()
                sess = f"💾 {len(sessions)} 会话"
            except Exception:
                sess = "💾 -"

            line = f"{mode} │ {ctx} │ {bar_rich} │ {arc} │ {sess} │ {warn.strip()}"
        except Exception as e:
            line = f"footer-bar 初始化中... ({e})"

        footer = self.query_one("#footer-bar", Static)
        footer.update(line)

    # ---------- 处理 InputArea.Submit ----------

    def on_input_area_submit(self, message: InputArea.Submit) -> None:
        text = message.text.strip()
        if not text or self._busy:
            return
        ta = self.query_one("#textarea", TextArea)
        ta.text = ""
        self._set_busy(True)
        self._log_user(text)
        self._show_thinking()

        # 命令分流（/ 开头的不进入 agent.run）
        if text.startswith('/'):
            self.run_worker(lambda: self._run_command(text), thread=True, exclusive=True)
            return

        # 阻塞检查：needs_compact 时不允许普通输入
        if self.agent.needs_compact:
            def on_event(ev):
                t = ev.get('type', '')
                if t == 'assistant':
                    self.call_from_thread(self._log_assistant, ev['content'])
                else:
                    self.call_from_thread(self._log_tool, ev.get('name', ''), ev.get('result', ''))
            self.run_worker(lambda: self.agent.run(text, on_event), thread=True, exclusive=True)
            return

        self.run_worker(lambda: self._process(text), thread=True, exclusive=True)

    # ---------- 斜杠命令 ----------

    def _run_command(self, cmd: str) -> None:
        """处理 / 开头的命令。"""
        def on_event(ev):
            t = ev.get('type', '')
            if t == 'info':
                self.call_from_thread(self._log_info, ev['content'])
            elif t == 'assistant':
                self.call_from_thread(self._log_assistant, ev['content'])
            elif t == 'tool_call':
                self.call_from_thread(self._log_tool, ev['name'], ev['result'])

        try:
            # --- 帮助 ---
            if cmd in ('/help', '/?'):
                lines = ["可用斜杠命令："]
                for name, desc in SLASH_COMMANDS:
                    lines.append(f"  {name:<14} {desc}")
                self.call_from_thread(self._log_info, "\n".join(lines))

            # --- 会话管理 ---
            elif cmd.startswith('/new'):
                # 自动保存当前会话
                if self.agent.messages:
                    try:
                        sid = session_mod.save_session(self.agent.messages)
                        self.call_from_thread(self._log_info, f"已保存当前会话 → {sid}")
                    except Exception as e:
                        self.call_from_thread(self._log_info, f"保存失败（继续新建）：{e}")
                self.agent.reset()
                self.call_from_thread(self._log_info, "✓ 新会话已开启")

            elif cmd.startswith('/save'):
                if not self.agent.messages:
                    self.call_from_thread(self._log_info, "当前没有对话可保存。")
                else:
                    sid = session_mod.save_session(self.agent.messages)
                    self.call_from_thread(self._log_info, f"✓ 会话已保存 → {sid}")

            elif cmd.startswith('/resume'):
                sessions = session_mod.list_sessions()
                if not sessions:
                    self.call_from_thread(self._log_info, "暂无历史会话可恢复。")
                else:
                    # 展示列表
                    lines = ["可用历史会话（输入编号恢复，/cancel 取消）："]
                    for i, s in enumerate(sessions):
                        lines.append(f"  [{i+1}] {s['id']}  {s['message_count']}条  {s['preview']}")
                    self.call_from_thread(self._log_info, "\n".join(lines))
                    self.call_from_thread(self._log_info, "（目前需要手动选编号后让 AI 执行：/resume <编号>）")

            elif cmd.startswith('/resume '):
                try:
                    idx = int(cmd.strip().split()[1]) - 1
                except (ValueError, IndexError):
                    self.call_from_thread(self._log_info, "用法: /resume <编号>（编号从 1 开始）")
                else:
                    sessions = session_mod.list_sessions()
                    if not (0 <= idx < len(sessions)):
                        self.call_from_thread(self._log_info, f"编号越界（共 {len(sessions)} 个会话）")
                    else:
                        sid = sessions[idx]['id']
                        msgs = session_mod.load_session(sid)
                        self.agent.messages = msgs
                        self.call_from_thread(self._log_info, f"✓ 已恢复会话 {sid}（{len(msgs)} 条消息）")

            elif cmd.startswith('/reset'):
                self.agent.reset()
                self.call_from_thread(self._log_info, "对话历史已清空（未保存；可用 /save 先保存）")

            # --- 压缩 & 归档 ---
            elif cmd.startswith('/compact'):
                self.call_from_thread(self._log_info, "压缩中（期间不接受其他输入）...")
                self.agent.compact(on_event)

            elif cmd.startswith('/archives'):
                from ..core import context as ctx_mod
                arcs = ctx_mod.list_archives()
                if not arcs:
                    self.call_from_thread(self._log_info, "暂无上下文归档（执行过 /compact 之后会出现）。")
                else:
                    lines = [f"- {a['id']}  {a['time']}  ({a['message_count']} 条)" for a in arcs]
                    self.call_from_thread(self._log_info, "上下文归档：\n" + "\n".join(lines))

            elif cmd.startswith('/sessions'):
                sessions = session_mod.list_sessions()
                if not sessions:
                    self.call_from_thread(self._log_info, "暂无已保存会话（用 /save 保存当前会话）。")
                else:
                    lines = [f"- {s['id']}  {s['time'] or '—'}  ({s['message_count']} 条)  {s['preview']}" for s in sessions]
                    self.call_from_thread(self._log_info, "已保存会话：\n" + "\n".join(lines))

            # --- MCP / Skills 状态 ---
            elif cmd.startswith('/mcp'):
                servers = self.agent.mcp_server_list
                if not servers:
                    self.call_from_thread(self._log_info, "未配置 .mcp.json，或所有 Server 连接失败。")
                else:
                    lines = ["MCP Servers:"]
                    for name, status, tools in servers:
                        mark = "✓" if status == "connected" else "✗"
                        lines.append(f"  {mark} {name} → {status} ({len(tools)} tools)")
                        for t in tools:
                            short = t.split('__', 1)[1] if '__' in t else t
                            lines.append(f"      ↳ {short}")
                    self.call_from_thread(self._log_info, "\n".join(lines))

            elif cmd.startswith('/skills'):
                skills = self.agent.skills_list
                if not skills:
                    self.call_from_thread(self._log_info, "未发现 Skill（检查 .agents/skills/<name>/SKILL.md 是否存在）。")
                else:
                    lines = ["已注册 Skills:"]
                    for n, d in skills:
                        lines.append(f"  • {n} — {d[:60]}{'…' if len(d) > 60 else ''}")
                    self.call_from_thread(self._log_info, "\n".join(lines))

            # --- 退出 ---
            elif cmd.startswith('/quit') or cmd.startswith('/exit'):
                if self.agent.messages:
                    try:
                        sid = session_mod.save_session(self.agent.messages)
                        self.call_from_thread(self._log_info, f"已自动保存会话 → {sid}")
                    except Exception:
                        pass
                self.call_from_thread(self._log_info, "再见！")
                self.call_from_thread(self.exit)

            else:
                self.call_from_thread(self._log_info,
                    f"未知命令：{cmd}。输入 /help 查看全部命令。")
        except Exception as e:
            self.call_from_thread(self._log_assistant, f"命令执行出错: {e}")
        finally:
            self.call_from_thread(self._done)
            self.call_from_thread(self._refresh_sidebar)

    # ---------- 快捷键 ----------

    def action_toggle_readonly(self) -> None:
        self.agent.readonly = not self.agent.readonly
        self._update_title_mode()
        label = "只读模式（AI 不会创建/修改文件）" if self.agent.readonly else "读写模式（AI 可操作文件）"
        self._add(Static(f"已切换：{label}", classes="msg-system"))

    def action_compact(self) -> None:
        if self._busy:
            self._add(Static("正在处理其他任务，请等待完成后再压缩。", classes="msg-system"))
            return
        self._run_command("/compact")

    def action_save_session(self) -> None:
        self._run_command("/save")

    def action_copy_last(self) -> None:
        try:
            last_ai = self._find_last_assistant_message()
            if last_ai:
                import pyperclip
                pyperclip.copy(last_ai)
                self._add(Static("✓ 已复制最后一条 AI 回复到剪贴板。", classes="msg-system"))
            else:
                self._add(Static("目前还没有 AI 回复可以复制。", classes="msg-system"))
        except ImportError:
            self._add(Static("需要先 `pip install pyperclip` 才能使用 Ctrl+Y 复制功能。", classes="msg-system"))
        except Exception as e:
            self._add(Static(f"复制失败：{e}", classes="msg-system"))

    def _find_last_assistant_message(self):
        for m in reversed(self.agent.messages):
            if m.get('role') == 'assistant' and m.get('content'):
                return m['content']
        return None

    def action_clear(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.remove_children()
        chat.mount(Static("已清屏。", classes="msg-system"))

    # ---------- 消息渲染 ----------

    def _add(self, widget) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(widget)
        self.call_after_refresh(self._scroll_end)
        self.set_timer(0.3, self._scroll_end)

    def _scroll_end(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    def _log_user(self, text: str) -> None:
        self._add(Static(f"你：{text}", classes="msg msg-user"))

    def _log_tool(self, name: str, result: str) -> None:
        # result 可能很长（如 JSON），截断显示
        display = result if len(result) < 300 else result[:300] + "…"
        self._add(Static(f"工具 {name}：{display}", classes="msg msg-tool"))

    def _log_assistant(self, content: str) -> None:
        self._add(Markdown(f"**AI：**\n\n{content}", classes="msg msg-ai"))

    def _log_info(self, content: str) -> None:
        self._add(Static(f"ℹ️ {content}", classes="msg-info"))

    def _log_warn(self, content: str) -> None:
        self._add(Static(f"⚠️ {content}", classes="msg-warn"))

    def _show_thinking(self) -> None:
        self._add(Static("思考中…", id="thinking"))

    def _hide_thinking(self) -> None:
        try:
            self.query_one("#chat", VerticalScroll).query("#thinking").remove()
        except Exception:
            pass

    def _done(self) -> None:
        self._set_busy(False)
        self._hide_thinking()
        self._update_title_mode()
        self._refresh_sidebar()

    def _set_busy(self, busy: bool) -> None:
        """标记忙碌状态，控制 spinner 可见性。"""
        self._busy = busy
        spinner = self.query_one("#spinner", LoadingIndicator)
        if busy:
            spinner.add_class("busy")
        else:
            spinner.remove_class("busy")

    # ---------- 后台 worker ----------

    def _process(self, text: str) -> None:
        def on_event(ev: dict) -> None:
            if ev["type"] == "tool_call":
                self.call_from_thread(self._log_tool, ev["name"], ev["result"])
            else:
                self.call_from_thread(self._log_assistant, ev["content"])

        try:
            self.agent.run(text, on_event)
        except Exception as e:
            self.call_from_thread(self._log_assistant, f"出错了: {e}")
        finally:
            self.call_from_thread(self._done)
