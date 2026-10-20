import configparser
import subprocess
import json
from openai import OpenAI

config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')

client = OpenAI(
    api_key=config['llm']['api_key'],
    base_url=config['llm']['base_url']
)

# function call tool: 调用本地 date 命令获取当前日期和时间
def get_date():
    result = subprocess.run('date /t & time /t', shell=True, capture_output=True, text=True)
    return result.stdout.strip()

# function call tool: 用 Python 代码计算输入的年份是否是闰年
def is_leap_year(year):
    year = int(year)
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)

tools = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "计算输入的年份是否是闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "要计算的年份，例如 2024"
                    }
                },
                "required": ["year"]
            }
        }
    }
]

messages = []

while True:
    user_input = input("你: ")
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
                if tool_call.function.name == "getDate":
                    result = get_date()
                elif tool_call.function.name == "isLeapYear":
                    args = json.loads(tool_call.function.arguments)
                    result = f"{args['year']} 年是闰年" if is_leap_year(args['year']) else f"{args['year']} 年不是闰年"
                else:
                    result = "未知工具"
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
