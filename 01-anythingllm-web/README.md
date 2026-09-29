# AnythingLLM 工作台（单文件网页）

课程一作业：用一个**零依赖的原生 HTML 文件**调用本机 AnythingLLM API，实现：

- 💬 **工作区对话**：下拉选择工作区，直接在网页上与知识库问答（显示引用来源）
- 📤 **上传文档并向量化**：选择本地文件 → 调用 `/v1/document/upload` 上传 → 自动提取文档引用并调用 `update-embeddings` 完成嵌入，全流程日志可见

## 使用方法

1. 确保本机 AnythingLLM 已启动（默认 `http://localhost:3001`），并已在设置中生成 API Key。
2. 双击用浏览器打开 `index.html`。
3. 首次打开会弹窗要求输入 **AnythingLLM API Key**，Key 只保存在当前浏览器的 `localStorage` 中，不会随页面源码泄露。
4. 顶部下拉框加载出工作区后即可对话或上传文档。

> 重新输入 / 更换 Key：在浏览器控制台执行 `localStorage.removeItem("ANYTHINGLLM_API_KEY")` 后刷新页面。

## 技术要点

- 原生 HTML / CSS / JavaScript，无框架、无构建步骤
- `fetch` + `FormData` 完成 multipart 文件上传
- 上传响应中 `name` 字段可能缺失，代码以 `name || title` 兜底提取文档标识
- 安全：API Key 不硬编码，运行时输入并保存在本机浏览器
