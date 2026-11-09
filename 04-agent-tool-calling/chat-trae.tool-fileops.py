import configparser
import os
import subprocess
import shutil
import json
from openai import OpenAI

config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')

client = OpenAI(
    api_key=config['llm']['api_key'],
    base_url=config['llm']['base_url']
)

# 安全沙箱：所有文件操作只允许在脚本所在目录内进行，防止误删/误改项目其他文件
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def safe_path(path):
    """把传入路径解析为绝对路径，并校验必须位于沙箱目录内"""
    abs_path = os.path.abspath(path)
    if os.path.commonpath([BASE_DIR, abs_path]) != BASE_DIR:
        raise ValueError(f"路径越界: {path}（只允许操作 {BASE_DIR} 内的文件）")
    return abs_path

# 纯文本文件扩展名白名单
TEXT_EXTS = {'.txt', '.md', '.mmd', '.py', '.json', '.ini', '.cfg', '.csv',
             '.html', '.css', '.js', '.xml', '.yml', '.yaml', '.log', '.bat'}

# ---------- function call 工具实现 ----------

# 1. 获取当前工作目录：调用本地 cmd 的 cd 命令
def get_cwd():
    result = subprocess.run('cd', shell=True, capture_output=True, text=True)
    return result.stdout.strip()

# 2. 列出指定目录下所有文件和子目录
def list_dir(args):
    abs_path = safe_path(args.get('path', '.'))
    if not os.path.isdir(abs_path):
        return f"错误: {args.get('path', '.')} 不是目录"
    entries = []
    for name in sorted(os.listdir(abs_path)):
        full = os.path.join(abs_path, name)
        entries.append(f"[目录] {name}" if os.path.isdir(full) else f"[文件] {name}")
    return "\n".join(entries) if entries else "（空目录）"

# 3. 获取指定文件的文件类型
TYPE_MAP = {'.txt': '文本文档', '.md': 'Markdown 文档', '.mmd': 'Mermaid 图表源文件',
            '.py': 'Python 源文件', '.json': 'JSON 文件', '.ini': '配置文件',
            '.html': '网页文件', '.css': '样式表文件', '.js': 'JavaScript 文件',
            '.csv': 'CSV 表格文件', '.log': '日志文件', '.bat': '批处理文件'}

def get_file_type(args):
    abs_path = safe_path(args['path'])
    if os.path.isdir(abs_path):
        return f"{args['path']} 是目录"
    if not os.path.isfile(abs_path):
        return f"错误: {args['path']} 不存在"
    ext = os.path.splitext(abs_path)[1].lower()
    desc = TYPE_MAP.get(ext, '未知类型文件')
    return f"{args['path']} 是{desc}（扩展名: {ext or '无'}）"

def _read_text(abs_path):
    """按 utf-8 / gbk 顺序尝试读取纯文本文件"""
    for enc in ('utf-8', 'gbk'):
        try:
            with open(abs_path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码（可能不是纯文本文件）")

# 4. 获取指定文件的内容（仅支持纯文本格式文件）
def read_file(args):
    abs_path = safe_path(args['path'])
    if not os.path.isfile(abs_path):
        return f"错误: {args['path']} 不存在"
    if os.path.splitext(abs_path)[1].lower() not in TEXT_EXTS:
        return f"错误: {args['path']} 不是支持的纯文本格式"
    return _read_text(abs_path)

# 5. 根据指定的目录和文件名创建新文件
def create_file(args):
    abs_path = safe_path(os.path.join(args.get('directory', '.'), args['filename']))
    if os.path.exists(abs_path):
        return f"错误: {args['filename']} 已存在，如需修改请用 editFile"
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, 'w', encoding='utf-8') as f:
        f.write(args.get('content', ''))
    return f"已创建文件 {args['filename']}"

# 6. 编辑指定文件的内容（仅支持纯文本格式文件，整文件覆盖写入）
def edit_file(args):
    abs_path = safe_path(args['path'])
    if not os.path.isfile(abs_path):
        return f"错误: {args['path']} 不存在，请先用 createFile 创建"
    if os.path.splitext(abs_path)[1].lower() not in TEXT_EXTS:
        return f"错误: {args['path']} 不是支持的纯文本格式"
    with open(abs_path, 'w', encoding='utf-8') as f:
        f.write(args['content'])
    return f"已更新文件 {args['path']}"

# 7. 创建新目录
def make_dir(args):
    abs_path = safe_path(args['path'])
    os.makedirs(abs_path)
    return f"已创建目录 {args['path']}"

# 8. 删除目录（支持非空目录）
def remove_dir(args):
    abs_path = safe_path(args['path'])
    if abs_path == BASE_DIR:
        return "错误: 不允许删除脚本所在目录"
    if not os.path.isdir(abs_path):
        return f"错误: {args['path']} 不是目录"
    shutil.rmtree(abs_path)
    return f"已删除目录 {args['path']}（含其中全部内容）"

# 9. 删除文件
def delete_file(args):
    abs_path = safe_path(args['path'])
    if not os.path.isfile(abs_path):
        return f"错误: {args['path']} 不是文件或不存在"
    os.remove(abs_path)
    return f"已删除文件 {args['path']}"

# 10. 重命名文件和目录（在同目录内改名）
def rename(args):
    abs_path = safe_path(args['path'])
    if not os.path.exists(abs_path):
        return f"错误: {args['path']} 不存在"
    new_path = safe_path(os.path.join(os.path.dirname(abs_path), args['new_name']))
    if os.path.exists(new_path):
        return f"错误: 目标名称 {args['new_name']} 已被占用"
    os.rename(abs_path, new_path)
    return f"已将 {args['path']} 重命名为 {args['new_name']}"

TOOL_IMPL = {
    "getCwd": lambda args: get_cwd(),
    "listDir": list_dir,
    "getFileType": get_file_type,
    "readFile": read_file,
    "createFile": create_file,
    "editFile": edit_file,
    "mkdir": make_dir,
    "rmdir": remove_dir,
    "deleteFile": delete_file,
    "rename": rename,
}

tools = [
    {"type": "function", "function": {
        "name": "getCwd",
        "description": "获取当前工作目录",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
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
]

messages = []

while True:
    try:
        user_input = input("你: ")
    except EOFError:
        break
    messages.append({"role": "user", "content": user_input})

    # 可能需要多轮工具调用，循环直到 AI 给出最终回答
    while True:
        response = client.chat.completions.create(
            model=config['llm']['model'],
            messages=messages,
            tools=tools
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            # 记录 AI 发起的工具调用
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls]
            })
            # 执行工具并把结果回传给 AI
            for tool_call in msg.tool_calls:
                try:
                    args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    impl = TOOL_IMPL.get(tool_call.function.name)
                    result = impl(args) if impl else "未知工具"
                except Exception as e:
                    result = f"工具执行出错: {e}"
                print(f"[调用工具 {tool_call.function.name}] 结果: {result}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            continue
        else:
            print("AI:", msg.content)
            messages.append({"role": "assistant", "content": msg.content})
            break
