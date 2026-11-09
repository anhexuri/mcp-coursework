"""CLI 命令执行工具：RunCli。

让 Agent 能够调用本地已安装的任意命令行程序，使用 subprocess 执行（shell=False）。
仅用于受控教学实验环境，不实现白名单/黑名单/审批机制。
"""
import subprocess

# 输出截断长度（字符数），防止大量终端输出占用 LLM 上下文
_MAX_OUTPUT = 4000
# 默认执行超时（秒）
_DEFAULT_TIMEOUT = 30


def run_cli(args):
    """执行本地 CLI 命令，返回 stdout / stderr / exit code。

    Args:
        args: dict，包含:
            - command (str): 程序名或路径，如 "python"、"git"、"dir"
            - args (list[str], optional): 参数列表，默认为空

    Returns:
        str: 格式化后的执行结果，包含 stdout、stderr、exit code
    """
    command = (args.get('command') or '').strip()
    cmd_args = args.get('args') or []
    timeout = args.get('timeout') or _DEFAULT_TIMEOUT

    if not command:
        return "错误: command 参数不能为空"

    # 拼为列表，shell=False 避免命令注入
    cmd = [command]
    if cmd_args:
        cmd.extend(cmd_args)

    try:
        result = subprocess.run(
            cmd, shell=False, capture_output=True, text=True,
            timeout=timeout, encoding='utf-8', errors='replace',
        )
    except FileNotFoundError:
        return f"错误: 找不到程序 '{command}'（请确认已安装且在 PATH 中）"
    except subprocess.TimeoutExpired:
        return f"错误: 命令执行超时（{timeout}秒），已被强制终止"
    except OSError as e:
        return f"错误: 命令执行失败: {e}"

    stdout = _truncate(result.stdout)
    stderr = _truncate(result.stderr)

    parts = [f"退出码: {result.returncode}"]
    if stdout:
        parts.append(f"标准输出:\n{stdout}")
    if stderr:
        parts.append(f"标准错误:\n{stderr}")

    # 无输出时提示一下
    if not stdout and not stderr:
        parts.append("（无标准输出和标准错误）")

    return "\n\n".join(parts)


def _truncate(text: str, max_len: int = _MAX_OUTPUT) -> str:
    """截断过长文本，标明截断情况"""
    if text is None:
        return ""
    if len(text) <= max_len:
        return text.rstrip()
    return text[:max_len] + f"\n\n... [输出已截断，总长 {len(text)} 字符，保留前 {max_len}]"
