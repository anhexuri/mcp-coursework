"""网络操作工具：searchWeb + fetchWeb。

不感知 LLM 和 UI，只负责 HTTP 请求和网页解析。
"""
import json
import os
import shutil
import subprocess

import requests
import trafilatura

from .config import load_search_config


def search_web(args):
    """调用百度千帆智能搜索 API，返回搜索摘要 + 参考来源。

    百度千帆 API 格式：
      POST {base_url}/web_search
      Header: Authorization: Bearer <api_key>, Content-Type: application/json
      Body: {"messages": [{"role": "user", "content": query}]}
    """
    query = args.get('query', '').strip()
    if not query:
        return "错误: query 参数不能为空"

    try:
        cfg = load_search_config()
    except Exception as e:
        return f"搜索功能未配置: {e}"

    url = f"{cfg.base_url}/web_search"
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    body = {"messages": [{"role": "user", "content": query}]}

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
    except requests.Timeout:
        return "网络超时: 百度搜索 API 30秒内未响应"
    except requests.RequestException as e:
        return f"网络请求失败: {e}"

    if resp.status_code != 200:
        return f"搜索 API 返回错误 ({resp.status_code}): {resp.text[:300]}"

    try:
        data = resp.json()
    except json.JSONDecodeError:
        return f"搜索 API 返回了非 JSON 内容: {resp.text[:200]}"

    # 百度千帆返回结构因模型和参数不同可能有差异，做兼容提取
    summary = ""
    references = []

    # 常见路径：result / answer / content / data.result
    if isinstance(data, dict):
        for key in ('result', 'answer', 'content'):
            if key in data and isinstance(data[key], str):
                summary = data[key].strip()
                break
        if not summary and isinstance(data.get('data'), dict):
            inner = data['data']
            for key in ('result', 'answer', 'content'):
                if key in inner and isinstance(inner[key], str):
                    summary = inner[key].strip()
                    break

        # 参考来源：references / sources
        refs_raw = data.get('references') or data.get('sources')
        if not refs_raw and isinstance(data.get('data'), dict):
            refs_raw = data['data'].get('references') or data['data'].get('sources')
        if refs_raw:
            for r in refs_raw[:10]:
                if isinstance(r, dict):
                    title = r.get('title') or r.get('name') or r.get('site', '')
                    src = r.get('url') or r.get('link') or r.get('source', '')
                    if title or src:
                        references.append(f"- {title} ({src})")
                elif isinstance(r, str):
                    references.append(f"- {r}")

    parts = []
    if summary:
        parts.append(summary)
    if references:
        parts.append("\n\n参考来源:\n" + "\n".join(references))

    if not parts:
        return f"搜索 API 未返回可用结果，原始响应: {resp.text[:300]}"

    return "\n".join(parts)


def fetch_web(args):
    """获取指定网页正文并转为 Markdown。

    使用 subprocess 调用本地 curl（参数列表形式，不用 shell=True），
    再用 trafilatura 提取正文，保留标题/段落/列表/表格/链接。
    """
    url = args.get('url', '').strip()
    if not url:
        return "错误: url 参数不能为空"

    # 定位 curl
    curl = shutil.which('curl') or r'C:\Windows\System32\curl.exe'
    if not os.path.isfile(curl):
        return f"错误: 找不到 curl 程序，请确保系统已安装 curl"

    # 用参数列表方式调用，避免 shell 注入
    try:
        result = subprocess.run(
            [curl, '-sL', '--max-time', '20', '-H',
             'User-Agent: Mozilla/5.0 (compatible; AgentEvanescia/1.0)',
             url],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "错误: 网页访问超时（30秒）"
    except OSError as e:
        return f"错误: curl 执行失败: {e}"

    if result.returncode != 0:
        stderr = result.stderr.strip()[:200]
        return f"错误: curl 执行失败 (code={result.returncode}): {stderr}"

    html = result.stdout
    if not html or len(html) < 200:
        return "错误: 网页内容为空或过短（可能访问被拒绝或重定向失败）"

    # 用 trafilatura 提取正文
    try:
        text = trafilatura.extract(
            html, output_format='markdown', include_links=True,
            include_tables=True, deduplicate=True, favor_precision=True,
        )
    except Exception as e:
        return f"错误: 网页解析失败 (trafilatura): {e}"

    if not text or not text.strip():
        return f"错误: 无法从该网页提取正文（可能是纯动态 JS 页面或反爬）。原始 HTML 长度: {len(html)} 字节"

    # 截断过长内容，保留前 8000 字符
    if len(text) > 8000:
        text = text[:8000] + f"\n\n--- 内容过长已截断，原始长度 {len(text)} 字符 ---"

    return f"来源: {url}\n\n{text}"
