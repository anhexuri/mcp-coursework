"""技能（Skill）发现与动态加载。

设计要点：
1. 项目根目录取程序启动时的工作目录（即本模块导入时的 os.getcwd()），
   在其下的 .agents/skills/ 中扫描技能子目录；
2. 初始化时只解析各 SKILL.md 的 YAML frontmatter（name / description），
   不读取正文；
3. 正文与附加文件仅在 LLM 调用 loadSkill 工具时才读取，且读取范围
   严格限制在对应技能目录内。
"""
import os
from dataclasses import dataclass
from typing import List

# 程序启动时的工作目录即项目根目录（模块在启动阶段导入）
PROJECT_ROOT = os.getcwd()
SKILLS_DIRNAME = os.path.join('.agents', 'skills')
SKILL_FILENAME = 'SKILL.md'


@dataclass
class Skill:
    name: str
    description: str
    directory: str

    @property
    def skill_file(self) -> str:
        return os.path.join(self.directory, SKILL_FILENAME)


def _parse_frontmatter(lines: List[str]) -> dict:
    """极简 YAML frontmatter 解析：仅取顶层 key: value"""
    if not lines or lines[0].strip().lstrip('\ufeff') != '---':
        return {}
    data = {}
    current = None
    for line in lines[1:]:
        if line.strip() == '---':
            break
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if line[0] in ' \t' and current:  # 续行
            data[current] = f"{data[current]} {stripped}".strip()
            continue
        key, sep, value = line.partition(':')
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        data[key] = value
        current = key
    return data


def _read_frontmatter(path: str) -> dict:
    """只读取 frontmatter 部分，遇到结束分隔符即停止，不读正文"""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            lines = []
            for line in f:
                lines.append(line)
                if len(lines) > 1 and line.strip() == '---':
                    break
    except OSError:
        return {}
    return _parse_frontmatter(lines)


def discover_skills() -> List[Skill]:
    """递归扫描 .agents/skills/ 下所有 SKILL.md，仅加载 name / description

    兼容 namespace 安装（如 .agents/skills/@org/skill/SKILL.md）。
    """
    skills = []
    base = os.path.join(PROJECT_ROOT, SKILLS_DIRNAME)
    if not os.path.isdir(base):
        return skills

    seen = set()
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
        if SKILL_FILENAME not in filenames:
            continue
        skill_file = os.path.join(dirpath, SKILL_FILENAME)
        meta = _read_frontmatter(skill_file)
        name = (meta.get('name') or '').strip()
        description = (meta.get('description') or '').strip()
        if not name or not description or name in seen:
            continue
        seen.add(name)
        skills.append(Skill(name=name, description=description, directory=dirpath))
    return skills


_SKILLS = None


def get_skills() -> List[Skill]:
    """技能列表（首次调用时发现并缓存）"""
    global _SKILLS
    if _SKILLS is None:
        _SKILLS = discover_skills()
    return _SKILLS


def build_skills_prompt(skills: List[Skill]) -> str:
    """把技能名称与描述整理成注入系统提示的文本"""
    if not skills:
        return ""
    lines = ["你可以使用以下技能:"]
    for skill in skills:
        lines.append(f'- "{skill.name}": {skill.description}')
    lines.append("")
    lines.append('使用 "loadSkill" 工具可在需要时加载技能的全部说明；也可加载技能引用的其他文件。')
    lines.append("加载结果会包含技能目录的绝对路径，技能内的脚本可通过 runCli 以该路径执行。")
    lines.append("技能正文不会预先加载，确认需要使用某个技能时再调用 loadSkill。")
    return "\n".join(lines)


def _is_inside(directory: str, path: str) -> bool:
    """路径必须位于技能目录内（解析软链接后再比较）"""
    root = os.path.realpath(directory)
    target = os.path.realpath(path)
    try:
        return os.path.commonpath([root, target]) == root
    except ValueError:
        return False


def _read_text(abs_path: str) -> str:
    for enc in ('utf-8-sig', 'gbk'):
        try:
            with open(abs_path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return "错误: 无法识别文件编码（可能不是纯文本文件）"


def load_skill(args: dict) -> str:
    """loadSkill 工具实现：按需读取 SKILL.md 正文或附加文件"""
    name = (args.get('name') or '').strip()
    filename = (args.get('filename') or '').strip()
    if not name:
        return "错误: 缺少技能名称 name"

    skills = get_skills()
    skill = next((s for s in skills if s.name == name), None)
    if skill is None:
        skill = next((s for s in skills if s.name.lower() == name.lower()), None)
    if skill is None:
        available = '、'.join(s.name for s in skills) or '（无）'
        return f'错误: 未找到技能 "{name}"。可用技能: {available}'

    # 仅提供名称：读取该技能 SKILL.md 全文，并给出技能目录便于执行脚本
    if not filename:
        return f"技能目录: {skill.directory}\n\n{_read_text(skill.skill_file)}"

    # 精确路径匹配：支持技能目录相对路径、项目相对路径、绝对路径
    if os.path.isabs(filename):
        candidates = [filename]
    else:
        candidates = [os.path.join(skill.directory, filename),
                      os.path.join(PROJECT_ROOT, filename)]

    for candidate in candidates:
        if os.path.isfile(candidate):
            if not _is_inside(skill.directory, candidate):
                return f"错误: 文件 {filename} 不在技能目录内，拒绝读取"
            return _read_text(os.path.abspath(candidate))

    # 仅提供文件名：在技能目录内递归搜索，唯一命中则读取
    if os.path.basename(filename) == filename:
        matches = []
        for dirpath, _, files in os.walk(skill.directory):
            for f in files:
                if f == filename:
                    matches.append(os.path.join(dirpath, f))
        if len(matches) == 1:
            return _read_text(matches[0])
        if len(matches) > 1:
            listing = "\n".join(f"- {os.path.relpath(m, skill.directory)}" for m in matches)
            return f'找到多个名为 "{filename}" 的文件，请用 filename 指定其一:\n{listing}'

    return f'错误: 在技能 "{skill.name}" 目录内未找到文件 "{filename}"'
