import json
import os

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageToolCall

from devharness import config
from devharness.skills import skills_prompt
from devharness.tools import TOOLS, TOOL_SCHEMAS

# print("########################## ", config.BASE_URL, " ##########################")
client = OpenAI(
    base_url=config.BASE_URL,
    api_key=config.API_KEY,
)

# writing_line = "\nUse write_file to create files and str_replace to edit them."
writing_line = ""


SYSTEM_PROMPT = f"""
You are a coding agent. Your job is to code. Always code.
Use the bash tool to inspect files.{writing_line}
Answer back to the user once exploration is done.

Your current working directory is: {os.getcwd()}

You have skills available. Each one is a set of instructions for a task.
If a skill matches what the user wants, call read_skill first and follow it.

{skills_prompt()}
"""


def call_llm(messages):
    response = client.chat.completions.create(
        model=config.MODEL,
        messages=messages,
        tools=TOOL_SCHEMAS, # type: ignore
    )

    message = response.choices[0].message

    completion_details = getattr(response.usage, "completion_tokens_details", None)
    prompt_details = getattr(response.usage, "prompt_tokens_details", None)
    
    usage = {
        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
        "completion_tokens": getattr(response.usage, "completion_tokens", 0),
        "reasoning_tokens": getattr(completion_details, "reasoning_tokens", None),
        "cached_tokens": getattr(prompt_details, "cached_tokens", None),
    }

    return message, usage


if __name__ == "__main__":
    user_input = input("Enter your prompt> ")

    message, usage = call_llm([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ])

    print("\nAgent: ", message.content, "\n")

    if message.tool_calls:
        tool_call = message.tool_calls[0]
        if isinstance(tool_call, ChatCompletionMessageToolCall):
            args = json.loads(tool_call.function.arguments)
            result = TOOLS[tool_call.function.name](**args)
            print("Tool: ", tool_call.function.name, args)
            print(result, "\n")
        else:
            print("Custom tool call detected")

    print(usage)