"""会话持久化：/save /new /resume /quit 依赖的存储层。

存储位置：<项目根>/.agents/sessions/*.jsonl，每次 /save 或 /new 触发保存。
格式与 context.archive 类似：首行 _meta，后续每行一条 message dict。
"""
import json
import os
from datetime import datetime


def _sessions_root(project_root: str = None) -> str:
    root = os.path.join(project_root or os.getcwd(), ".agents", "sessions")
    os.makedirs(root, exist_ok=True)
    return root


def _make_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def save_session(messages: list, project_root: str = None, label: str = None) -> str:
    """保存当前消息列表，返回 session_id（文件名）。"""
    sid = _make_id()
    root = _sessions_root(project_root)
    path = os.path.join(root, f"{sid}.jsonl")
    with open(path, 'w', encoding='utf-8') as f:
        header = {
            '_meta': True,
            'session_id': sid,
            'saved_at': datetime.now().isoformat(timespec='seconds'),
            'message_count': len(messages),
            'label': label or '',
        }
        f.write(json.dumps(header, ensure_ascii=False) + '\n')
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + '\n')
    return sid


def list_sessions(project_root: str = None) -> list:
    """列出所有已保存会话，按时间倒序。

    返回 [{'id': ..., 'time': ..., 'label': ..., 'message_count': N, 'preview': str}, ...]
    preview 取最后一条 assistant.content 前 60 字。
    """
    root = _sessions_root(project_root)
    sessions = []
    for name in sorted(os.listdir(root), reverse=True):
        if not name.endswith('.jsonl'):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            if not lines:
                continue
            meta = json.loads(lines[0])
            messages = [json.loads(ln) for ln in lines[1:] if ln]
            # 取最后一条有 content 的消息做预览
            preview = ''
            for m in reversed(messages):
                if m.get('role') == 'assistant' and m.get('content'):
                    preview = str(m['content'])[:60]
                    break
            sessions.append({
                'id': meta.get('session_id', name[:-6]),
                'time': meta.get('saved_at', ''),
                'label': meta.get('label', ''),
                'message_count': meta.get('message_count', len(messages)),
                'preview': preview,
            })
        except Exception:
            sessions.append({'id': name[:-6], 'time': '', 'label': '',
                             'message_count': 0, 'preview': '(文件损坏)'})
    return sessions


def load_session(session_id: str, project_root: str = None) -> list:
    """读取指定会话，返回 messages 列表（去掉 _meta 行）。"""
    root = _sessions_root(project_root)
    path = os.path.join(root, f"{session_id}.jsonl")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"会话不存在: {path}")
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


def delete_session(session_id: str, project_root: str = None) -> bool:
    root = _sessions_root(project_root)
    path = os.path.join(root, f"{session_id}.jsonl")
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
