import configparser
from openai import OpenAI

config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')

client = OpenAI(
    api_key=config['llm']['api_key'],
    base_url=config['llm']['base_url']
)

messages = []

while True:
    user_input = input("你: ")
    messages.append({"role": "user", "content": user_input})

    print("AI: ", end="", flush=True)
    full_response = ""
    stream = client.chat.completions.create(
        model=config['llm']['model'],
        messages=messages,
        stream=True
    )

    for chunk in stream:
        if chunk.choices[0].delta.content:
            content = chunk.choices[0].delta.content
            print(content, end="", flush=True)
            full_response += content
    print()
    messages.append({"role": "assistant", "content": full_response})
