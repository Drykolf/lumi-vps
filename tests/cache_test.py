# debug_cache.py
import asyncio, os
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("DEEPINFRA_API_KEY"),
    base_url="https://api.deepinfra.com/v1/openai",
)

# Prefijo gordo y FIJO — 8K+ tokens repetidos
LONG_PREFIX = "You are a careful assistant. " * 1000

async def hit():
    r = await client.chat.completions.create(
        model="Qwen/Qwen3.5-35B-A3B",
        messages=[
            {"role": "system", "content": LONG_PREFIX},
            {"role": "user", "content": "Say 'ok' and nothing else."},
        ],
        max_tokens=10,
        temperature=0.7,
        extra_body={"top_k": 20,"prompt_cache_key": "test-fixed"},  # mismos params que tu config real
    )
    usage = r.usage
    cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
    print(f"prompt: {usage.prompt_tokens} | cached: {cached}")

async def main():
    for i in range(3):
        print(f"Request {i+1}:")
        await hit()
        await asyncio.sleep(1)

asyncio.run(main())