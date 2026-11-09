"""UI 抽象约定：所有界面（tui/web/desktop/mobile）复用同一个 core。

约定模式：UI 接收用户输入 → 调用 core.AgentCore.run(input, on_event) →
在 on_event 回调中把事件渲染到界面：
  {"type": "tool_call", "name": 工具名, "result": 执行结果}
  {"type": "assistant", "content": 最终回答}
"""
from abc import ABC, abstractmethod


class BaseUI(ABC):
    @abstractmethod
    def run(self):
        """启动界面并进入主循环"""
