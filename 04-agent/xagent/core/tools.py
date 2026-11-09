"""工具注册表：工具 schema（给 LLM 看）与实现（fileops / webops / cliops / mcp）的绑定

MCP 工具在 AgentCore.__init__ 阶段通过 register_mcp_tools() 动态追加，
与本地工具共享 TOOL_IMPL / TOOLS / available_tools 流程。
"""
from . import cliops, context as context_mod, fileops, skills, webops


def register_mcp_tools(entries):
    """把 MCP 发现的工具追加到 TOOL_IMPL 和 TOOLS。
    entries: list[(exposed_name, impl_callable, tool_schema_dict)]
    """
    for name, impl, schema in entries:
        TOOL_IMPL[name] = impl
        TOOLS.append(schema)

# 只读工具：只查询或联网，不改动文件系统
READONLY_TOOL_NAMES = {'getCwd', 'listDir', 'getFileType', 'readFile', 'searchWeb',
                       'fetchWeb', 'loadSkill', 'recallContext'}

TOOL_IMPL = {
    "getCwd": lambda args: fileops.get_cwd(),
    "loadSkill": skills.load_skill,
    "listDir": fileops.list_dir,
    "getFileType": fileops.get_file_type,
    "readFile": fileops.read_file,
    "searchWeb": webops.search_web,
    "fetchWeb": webops.fetch_web,
    "runCli": cliops.run_cli,
    "createFile": fileops.create_file,
    "editFile": fileops.edit_file,
    "mkdir": fileops.make_dir,
    "rmdir": fileops.remove_dir,
    "deleteFile": fileops.delete_file,
    "rename": fileops.rename,
    "createSkill": fileops.create_skill,
    "recallContext": context_mod.recall_context,
}

TOOLS = [
    {"type": "function", "function": {
        "name": "getCwd",
        "description": "获取当前工作目录",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "loadSkill",
        "description": "加载指定技能的完整说明（SKILL.md 正文），或读取该技能目录下的附加文件。仅在需要时调用，技能正文不会预先注入。",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "技能名称，即系统提示中列出的名称"},
            "filename": {"type": "string", "description": "可选。要读取的附加文件，支持相对技能目录的路径、项目相对路径或绝对路径；只提供文件名时会递归搜索技能目录"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "listDir",
        "description": "列出指定目录下所有文件和子目录",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "目录路径，默认当前目录"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "getFileType",
        "description": "获取指定文件的文件类型",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件或目录路径"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "readFile",
        "description": "获取指定文件的内容，仅支持纯文本格式文件（txt/md/py/json/ini/mmd 等）",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "createFile",
        "description": "根据指定的目录和文件名创建新文件，可同时写入初始内容（仅纯文本）",
        "parameters": {"type": "object", "properties": {
            "directory": {"type": "string", "description": "目标目录，默认当前目录"},
            "filename": {"type": "string", "description": "新文件名"},
            "content": {"type": "string", "description": "写入的初始内容，可选"}},
            "required": ["filename"]}}},
    {"type": "function", "function": {
        "name": "editFile",
        "description": "编辑指定文件的内容（整文件覆盖写入，仅支持纯文本格式文件）",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "新的完整内容"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "mkdir",
        "description": "创建新目录",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "新目录路径"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "rmdir",
        "description": "删除目录，非空目录会连同其中全部内容一起删除",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "要删除的目录路径"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "deleteFile",
        "description": "删除指定文件",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "要删除的文件路径"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "rename",
        "description": "重命名文件或目录（在同一目录内改名）",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "原文件或目录路径"},
            "new_name": {"type": "string", "description": "新名称（仅文件名或目录名）"}},
            "required": ["path", "new_name"]}}},
    {"type": "function", "function": {
        "name": "searchWeb",
        "description": "通过百度搜索获取互联网最新信息，返回搜索摘要和参考来源。适合查实时数据、新闻、百科等。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词或问题"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetchWeb",
        "description": "获取指定网页的主要内容并转为 Markdown，保留标题、段落、列表、表格和链接，去除导航栏/广告/页脚等无关内容。",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "网页完整 URL，如 https://example.com/article"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "runCli",
        "description": "调用本地已安装的命令行程序（CLI），如 python、git、dir、pip 等。返回标准输出、标准错误和退出码。注意：在 Windows 上 dir、cd、echo 等是 CMD 内置命令，需通过 'cmd' '参数' 方式调用，如 command='cmd' args=['/c','dir']。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "程序名或可执行文件路径，如 'python'、'git'、'cmd'"},
            "args": {"type": "array", "items": {"type": "string"}, "description": "命令参数列表，如 ['--version']、['-m','pip','list']，默认为空"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 30 秒"}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "createSkill",
        "description": "在当前项目的 .agents/skills/ 下创建一个新的 Skill 子目录和 SKILL.md 文件。name 必须是小写字母、数字和连字符组成（如 'mini-encryption'、'office-cli'）。skillContext 为 SKILL.md 的完整内容，必须以 YAML Frontmatter 开头并包含 name 和 description 字段。若同名 Skill 已存在会返回错误，不会覆盖。创建后可继续用 mkdir / createFile 添加 references/、scripts/ 等辅助目录和文件。",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Skill 名称，小写字母、数字、连字符，如 'mini-encryption'"},
            "skillContext": {"type": "string", "description": "SKILL.md 的完整内容，必须以 --- 分隔的 YAML Frontmatter 开头，包含 name 和 description 字段"}},
            "required": ["name", "skillContext"]}}},
    {"type": "function", "function": {
        "name": "recallContext",
        "description": "在之前保存的原始上下文归档中检索历史信息。当压缩摘要缺少某些细节、需要回溯旧对话内容时使用。text 为必填关键词；id 可选，指定归档编号（不填则在所有归档中搜索）。返回匹配的原始消息片段、归档编号和位置。单次返回最多约 2000 字符。",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "可选。归档编号，如 '20261022-153000'。不填则在 .agents/context/ 下所有归档中搜索"},
            "text": {"type": "string", "description": "必填。要查找的关键词或文本"}},
            "required": ["text"]}}},
]
