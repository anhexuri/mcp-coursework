"""xAgent 入口：启动 TUI 界面。

启动流程：
  1. Windows 终端 UTF-8 修复
  2. 检查 config.ini，不存在就自动生成 mock 版并提示用户填写 api_key
  3. 初始化 AgentCore（内部会扫 skills / 连接 MCP / 读 AGENTS.md）
  4. 启动 TUI
"""
import os
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from xagent.core.config import PROJECT_ROOT, ensure_config_exists


def _first_run_dialog(path: str) -> None:
    msg = (
        "\n" + "=" * 60 + "\n"
        "  xAgent 首次启动：已自动生成 config.ini\n" + "=" * 60 + "\n"
        f"  位置: {path}\n\n"
        "  请打开 config.ini，把 [llm].api_key 改成你真实的\n"
        "  API Key，然后重新运行本程序。\n\n"
        "  留空直接启动会因认证失败而报错。\n" + "=" * 60 + "\n"
    )
    print(msg)
    try:
        input("按回车键退出...")
    except Exception:
        pass


if __name__ == "__main__":
    cfg_path = os.path.join(PROJECT_ROOT, 'config.ini')
    existed = ensure_config_exists(cfg_path)
    if not existed:
        _first_run_dialog(cfg_path)
        sys.exit(0)

    from xagent.core.config import load_config
    try:
        cfg = load_config(cfg_path)
        if not cfg.api_key or 'REPLACE_ME' in cfg.api_key:
            print("错误：config.ini 里 api_key 还是 mock 值，请先填真实 API Key 后重启。")
            try:
                input("按回车键退出...")
            except Exception:
                pass
            sys.exit(1)
    except Exception as e:
        print(f"错误：读取 config.ini 失败：{e}")
        sys.exit(1)

    # AgentCore 内部会同步 init_mcp + get_skills + 检查 AGENTS.md
    from xagent.core.llm import AgentCore
    from xagent.tui.app import FileOpsTUI

    FileOpsTUI(AgentCore()).run()
