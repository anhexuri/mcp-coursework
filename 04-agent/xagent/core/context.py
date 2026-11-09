"""上下文管理：Token 估算、原始归档、关键词检索。

暂不使用向量数据库，只用 Python 标准库。未来可替换 embedding + 向量库。
"""
import json
import os
import re
from datetime import datetime

# 归档目录（相对于启动时的工作目录，与 skills / .mcp.json 保持一致）
ARCHIVE_DIRNAME = ".agents\\context"


def get_archive_root(project_root: str = None) -> str:
    """返回归档目录绝对路径，不存在则创建。"""
    root = os.path.join(project_root or os.getcwd(), ARCHIVE_DIRNAME)
    os.makedirs(root, exist_ok=True)
    return root


def new_archive_id() -> str:
    """生成唯一编号：YYYYMMDD-HHMMSS"""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ---------- Token 估算 ----------

# 粗略估算：openai 的 tiktoken 对中文 ~1.5 tok/字、英文 ~0.25 tok/词。
# 这里用 中文字符 + 英文空格分词 来近似，够用就行（差 10-20% 不影响 80% 阈值判断）。
def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    # 中文字符每个算 1.5，英文按空格分词每个算 0.75，取 int
    zh = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_words = len(re.findall(r'[A-Za-z0-9_\-\.]+', text))
    return int(zh * 1.5 + en_words * 0.75 + len(text) * 0.05)


def count_messages_tokens(messages: list) -> int:
    """估算整组 messages 的 token 数（每条含 role + content + tool_calls 等字段）"""
    total = 0
    for msg in messages:
        total += 2  # 每条 role 成本
        content = msg.get('content') or ''
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get('type') == 'text':
                    total += estimate_tokens(c.get('text', ''))
        else:
            total += estimate_tokens(str(content))
        # tool_calls：arguments 和 function.name
        for tc in msg.get('tool_calls', []) or []:
            fn = tc.get('function', {})
            total += estimate_tokens(fn.get('name', ''))
            total += estimate_tokens(fn.get('arguments', ''))
        # tool role：tool_call_id
        if msg.get('role') == 'tool':
            total += estimate_tokens(msg.get('tool_call_id', ''))
    return total


# ---------- 原始归档 ----------

def save_archive(messages: list, project_root: str = None) -> str:
    """把完整原始消息保存为 jsonl，返回 archive_id。"""
    aid = new_archive_id()
    root = get_archive_root(project_root)
    path = os.path.join(root, f"{aid}.jsonl")
    with open(path, 'w', encoding='utf-8') as f:
        # 头部元信息
        header = {
            '_meta': True,
            'archive_id': aid,
            'created_at': datetime.now().isoformat(timespec='seconds'),
            'message_count': len(messages),
        }
        f.write(json.dumps(header, ensure_ascii=False) + '\n')
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
    return aid


def load_archive(archive_id: str, project_root: str = None) -> list:
    """读取指定归档文件，返回 message 列表（去掉 _meta 行）。"""
    root = get_archive_root(project_root)
    path = os.path.join(root, f"{archive_id}.jsonl")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"归档文件不存在: {path}")
    messages = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get('_meta'):
                continue
            messages.append(obj)
    return messages


def list_archives(project_root: str = None) -> list:
    """列出所有归档，按时间倒序。返回 [{'id': '...', 'path': '...', 'time': '...', 'message_count': N}, ...]"""
    root = get_archive_root(project_root)
    archives = []
    for name in sorted(os.listdir(root), reverse=True):
        if not name.endswith('.jsonl'):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                first = f.readline().strip()
            meta = json.loads(first)
            archives.append({
                'id': meta.get('archive_id', name[:-6]),
                'path': path,
                'time': meta.get('created_at', ''),
                'message_count': meta.get('message_count', 0),
            })
        except Exception:
            archives.append({'id': name[:-6], 'path': path, 'time': '', 'message_count': 0})
    return archives


# ---------- recallContext 全文检索 ----------

MAX_RETURN_CHARS = 2000  # 单次检索返回上限（字符），避免再次撑爆上下文
SNIPPET_CONTEXT = 2      # 匹配行前后各保留 N 行


def recall_context(args: dict) -> str:
    """recallContext 工具实现。args: {id?, text}"""
    text = (args.get('text') or '').strip()
    if not text:
        return "错误：参数 text（要检索的关键词）不能为空。"

    project_root = None  # 用 os.getcwd()
    archive_id = args.get('id', '').strip()
    try:
        if archive_id:
            archives = [{'id': archive_id, 'path': os.path.join(get_archive_root(project_root), f"{archive_id}.jsonl")}]
            if not os.path.isfile(archives[0]['path']):
                return f"归档 {archive_id} 不存在。可用归档：{[a['id'] for a in list_archives(project_root)]}"
        else:
            archives = [{'id': a['id'], 'path': a['path']} for a in list_archives(project_root)]
    except Exception as e:
        return f"读取归档目录失败：{e}"

    if not archives:
        return "暂无可用归档。"

    results = []
    total_hits = 0
    keyword_lower = text.lower()

    for arc in archives:
        try:
            with open(arc['path'], 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            results.append(f"[{arc['id']}] 读取失败: {e}")
            continue

        # 每行是一条 json
        # 简单做法：把 json 解出来 → 扁平成纯文本 → 在文本中找 keyword
        for idx, line in enumerate(lines):
            try:
                obj = json.loads(line.strip())
                if obj.get('_meta'):
                    continue
            except Exception:
                continue
            # 把所有字符串字段拼起来
            blob = _flatten_to_text(obj).lower()
            if keyword_lower in blob:
                total_hits += 1
                role = obj.get('role', 'unknown')
                content_preview = _flatten_to_text(obj)[:120]
                results.append(f"- [{arc['id']} L{idx+1} role={role}]: {content_preview}")
                if sum(len(r) for r in results) > MAX_RETURN_CHARS:
                    break
        if sum(len(r) for r in results) > MAX_RETURN_CHARS:
            break

    if not results:
        return f"在 {len(archives)} 个归档中未找到关键词「{text}」。"

    header = f"共 {total_hits} 处匹配（已截断，单次最多返回 {MAX_RETURN_CHARS} 字符）。使用 recallContext 的 id 参数可限定某个归档。\n\n"
    return header + "\n".join(results)


def _flatten_to_text(obj) -> str:
    """把 message dict 扁平化成纯文本，方便 keyword 匹配。"""
    parts = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith('_'):
                continue
            if isinstance(v, (str, int, float, bool)):
                parts.append(f"{k}={v}")
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        for kk, vv in item.items():
                            if isinstance(vv, (str, int, float, bool)):
                                parts.append(f"{kk}={vv}")
    return " | ".join(parts)
