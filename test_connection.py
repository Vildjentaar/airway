import os
from dotenv import load_dotenv
from openai import OpenAI
from llm_engine import call_llm
from system_prompt import SYSTEM_PROMPT

load_dotenv()

client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.getenv("GEMINI_API_KEY"),
)

messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {
        "role": "user",
        "content": "In English, greet and briefly introduce yourself with the airline, and ask the customer their request without exaggeration.",
        "hidden": True,
    },
]

print("Testing connection to Gemini API...")
result = call_llm(client, messages, [], None)
if result["success"]:
    print("Connection Successful!")
    print("Response:", result["messages"][-1]["content"])
else:
    print("Connection Failed!")
    print("Error:", result["error"])
