"""配置加载：config.ini 里的所有可配置参数都从这里取。

设计原则：硬编码常量 → config.ini 配置 + dataclass 默认值。
项目根目录不存在 config.ini 时，由 main.py 调用 ensure_config_exists() 自动生成 mock 版。
"""
import configparser
import os
from dataclasses import dataclass, field

# 项目根目录（xagent 包的上一级），同时也是文件操作沙箱的根
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    read_only: bool = False
    # 模型上下文窗口大小（tokens）。deepseek-chat / glm-4-air 都是 128k。
    context_window: int = 128000


@dataclass
class SearchConfig:
    """百度千帆智能搜索 API 配置"""
    api_key: str = ""
    base_url: str = "https://qianfan.baidubce.com/v2/ai_search"


@dataclass
class AgentConfig:
    """Agent 运行期可调参数——原来散落在 llm.py 里的硬编码常量。"""
    # 最大工具调用轮次（防死循环烧 token）
    max_tool_rounds: int = 10
    # 达到上下文窗口的多少时触发警告 / 阻塞输入
    usage_warn_ratio: float = 0.8
    # 压缩目标：摘要约多少 tokens
    compact_target_tokens: int = 5000
    # 是否在 System Prompt 里附加 AGENTS.md 内容（启动时检查项目根）
    load_agents_md: bool = True
    # 会话存储目录（相对于启动 cwd）
    sessions_dir: str = ".agents\\sessions"
    # MCP 配置路径（相对于启动 cwd）
    mcp_config_path: str = ".mcp.json"


def load_config(path: str = None) -> LLMConfig:
    """读取 config.ini 中的 [llm] 和 [agent] 配置段"""
    path = path or os.path.join(PROJECT_ROOT, 'config.ini')
    parser = configparser.ConfigParser()
    parser.read(path, encoding='utf-8')
    read_only = parser.getboolean('agent', 'read_only', fallback=False) if parser.has_section('agent') else False
    context_window = parser.getint('llm', 'context_window', fallback=128000) if parser.has_section('llm') else 128000
    return LLMConfig(
        api_key=parser['llm']['api_key'],
        base_url=parser['llm']['base_url'],
        model=parser['llm']['model'],
        read_only=read_only,
        context_window=context_window,
    )


def load_agent_config(path: str = None) -> AgentConfig:
    """读取 config.ini 中的 [agent] 段里 Agent 运行参数。缺省全用默认值。"""
    path = path or os.path.join(PROJECT_ROOT, 'config.ini')
    parser = configparser.ConfigParser()
    parser.read(path, encoding='utf-8')
    if not parser.has_section('agent'):
        return AgentConfig()
    return AgentConfig(
        max_tool_rounds=parser.getint('agent', 'max_tool_rounds', fallback=10),
        usage_warn_ratio=parser.getfloat('agent', 'usage_warn_ratio', fallback=0.8),
        compact_target_tokens=parser.getint('agent', 'compact_target_tokens', fallback=5000),
        load_agents_md=parser.getboolean('agent', 'load_agents_md', fallback=True),
        sessions_dir=parser.get('agent', 'sessions_dir', fallback='.agents\\sessions'),
        mcp_config_path=parser.get('agent', 'mcp_config_path', fallback='.mcp.json'),
    )


def load_search_config(path: str = None) -> SearchConfig:
    """读取 config.ini 中的 [search] 配置段。"""
    path = path or os.path.join(PROJECT_ROOT, 'config.ini')
    parser = configparser.ConfigParser()
    parser.read(path, encoding='utf-8')
    if not parser.has_section('search'):
        return SearchConfig()
    api_key = parser['search'].get('api_key', '').strip()
    if not api_key:
        return SearchConfig()
    return SearchConfig(
        api_key=api_key,
        base_url=parser['search'].get('base_url', 'https://qianfan.baidubce.com/v2/ai_search').strip(),
    )


# ---------------------------------------------------------------------------
# 自动生成缺失的 config.ini（带 mock 信息 + 注释）
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_INI = """\
# ============================================================
#  AgentEvanescia 配置文件
#  首次启动自动生成 mock 版，请替换 api_key 后重新启动
# ============================================================

[llm]
# 必填：以下三个字段必须填写正确才能正常调用模型
api_key = sk-REPLACE_ME_WITH_REAL_API_KEY
base_url = https://api.deepseek.com/v1/
model = deepseek-chat
# 可选：模型上下文窗口大小（tokens）。deepseek-chat 默认 128k，可显式配置
# context_window = 128000

[agent]
# true=只读模式（AI 看不到写操作工具，不会自作主张创建文件）；false=读写模式
read_only = true
# 最大工具调用轮次（防死循环烧 token，超过后强制停止）
max_tool_rounds = 10
# 上下文使用量达到窗口的多少时，显示警告并阻塞普通输入（0.0 ~ 1.0）
usage_warn_ratio = 0.8
# 压缩目标：让 LLM 生成约多少 tokens 的摘要
compact_target_tokens = 5000
# 是否在 System Prompt 里附加项目根目录下 AGENTS.md 的内容（一次注入、全程复用）
load_agents_md = true
# 会话持久化目录（相对于启动 cwd）
sessions_dir = .agents\\sessions
# MCP Server 配置文件路径（相对于启动 cwd）
mcp_config_path = .mcp.json

[search]
# 百度千帆智能搜索 API Key（AppBuilder API Key），格式如 bce-v3/ALTAK-xxx/yyy
# 在 https://console.bce.baidu.com/iam/#/iam/apikey/list 创建；未配置时联网搜索不可用
api_key =
base_url = https://qianfan.baidubce.com/v2/ai_search
"""


def ensure_config_exists(path: str = None) -> bool:
    """检查项目根目录下是否有 config.ini，没有就生成 mock 版。

    返回 True 表示"已经有 config.ini"，返回 False 表示"这次新生成的，用户需要填 api_key"。
    """
    path = path or os.path.join(PROJECT_ROOT, 'config.ini')
    if os.path.isfile(path):
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(DEFAULT_CONFIG_INI)
    return False
