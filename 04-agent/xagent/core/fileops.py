"""文件操作工具的具体实现（不感知 LLM 和 UI）"""
import os
import re
import shutil
import subprocess

from .skills import PROJECT_ROOT as WORKSPACE_ROOT, SKILLS_DIRNAME, SKILL_FILENAME

# Skill 名称规范：小写字母、数字、连字符（3-40 字符）
SKILL_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{1,39}$')

# 安全沙箱：所有文件操作只允许在项目目录内进行，防止误删/误改其他文件
# 项目目录取程序启动时的工作目录，与技能发现保持同一根目录
BASE_DIR = WORKSPACE_ROOT


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


# Office 文档后缀：禁止用纯文本工具创建/修改，必须通过 office-cli 技能
OFFICE_BINARY_EXTS = {'.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt'}
OFFICE_EXT_HINT = (
    "检测到目标是 Office 文档（{ext}），纯文本 {tool} 会损坏文件。"
    "请先 loadSkill name=office-cli，再用 runCli 执行 officecli-win-x64.exe。"
    "创建: officecli create <file>；修改: officecli add/set/remove；完成后务必 officecli close <file>。"
)


# 5. 根据指定的目录和文件名创建新文件
def create_file(args):
    filename = args['filename']
    ext = os.path.splitext(filename)[1].lower()
    if ext in OFFICE_BINARY_EXTS:
        return OFFICE_EXT_HINT.format(ext=ext, tool='createFile')
    abs_path = safe_path(os.path.join(args.get('directory', '.'), filename))
    if os.path.exists(abs_path):
        return f"错误: {filename} 已存在，如需修改请用 editFile"
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, 'w', encoding='utf-8') as f:
        f.write(args.get('content', ''))
    return f"已创建文件 {filename}"


# 6. 编辑指定文件的内容（仅支持纯文本格式文件，整文件覆盖写入）
def edit_file(args):
    abs_path = safe_path(args['path'])
    ext = os.path.splitext(abs_path)[1].lower()
    if ext in OFFICE_BINARY_EXTS:
        return OFFICE_EXT_HINT.format(ext=ext, tool='editFile')
    if not os.path.isfile(abs_path):
        return f"错误: {args['path']} 不存在，请先用 createFile 创建"
    if ext not in TEXT_EXTS:
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
        return "错误: 不允许删除项目根目录"
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


# 11. 创建 Skill：在 .agents/skills/<name>/ 下生成 SKILL.md
def create_skill(args):
    """createSkill 工具实现：创建符合 Agent Skills 规范的新技能。"""
    name = (args.get('name') or '').strip()
    context = (args.get('skillContext') or '').strip()

    # —— 1) 校验名称格式 ——
    if not name:
        return "错误: 缺少技能名称 name"
    if not SKILL_NAME_RE.match(name):
        return (
            f"错误: 技能名称 '{name}' 不符合规范。"
            "只能使用小写字母、数字和连字符（至少 2 字符，以字母或数字开头），"
            "例如 'mini-encryption'、'office-cli'。"
        )

    # —— 2) 校验 skillContext 非空 ——
    if not context:
        return "错误: 缺少 skillContext（SKILL.md 的完整内容）"

    # —— 3) 校验 frontmatter ——
    normalized = context.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')
    lines = normalized.split('\n')
    if len(lines) < 3 or lines[0].strip() != '---':
        return (
            "错误: skillContext 必须以 YAML Frontmatter 开头（第一行是 --- 分隔符）。\n"
            "示例:\n"
            "---\n"
            "name: my-skill\n"
            "description: 技能功能描述\n"
            "---\n"
            "\n"
            "正文..."
        )
    # 简单扫描 name / description 两个必需字段
    fm_name = fm_desc = None
    for line in lines[1:]:
        if line.strip() == '---':
            break
        if fm_name is None and line.strip().startswith('name:'):
            fm_name = line.split(':', 1)[1].strip().strip('"').strip("'")
        elif fm_desc is None and line.strip().startswith('description:'):
            fm_desc = line.split(':', 1)[1].strip().strip('"').strip("'")
    if not fm_name or not fm_desc:
        return (
            "错误: Frontmatter 必须同时包含 'name' 和 'description' 字段。"
        )
    # 文件名里的 name 和 frontmatter 里的 name 应一致（容错：不一致时以目录名为准）
    if fm_name != name:
        pass  # 不拒绝，给 LLM 自由度

    # —— 4) 目标路径与存在性检查 ——
    skill_dir = os.path.join(WORKSPACE_ROOT, SKILLS_DIRNAME, name)
    skill_file = os.path.join(skill_dir, SKILL_FILENAME)

    if os.path.isdir(skill_dir):
        if os.path.isfile(skill_file):
            return (
                f"错误: 技能 '{name}' 已存在（目录 {skill_dir}），"
                "如需修改请用 editFile 编辑 SKILL.md，或先删除再创建。"
            )
        return f"错误: 目录 {skill_dir} 已存在但不是有效技能（缺少 SKILL.md）"

    # —— 5) 创建目录并写入 SKILL.md ——
    os.makedirs(skill_dir, exist_ok=False)
    with open(skill_file, 'w', encoding='utf-8') as f:
        f.write(context + ('\n' if not context.endswith('\n') else ''))

    return (
        f"已创建技能 '{name}'：\n"
        f"  目录: {skill_dir}\n"
        f"  文件: {skill_file}\n"
        "如需添加 references/、scripts/ 等辅助目录或文件，可继续调用 mkdir / createFile。"
    )
