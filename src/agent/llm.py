from openai import AsyncOpenAI
import os
import logging
logger = logging.getLogger("llm")

# DeepInfra es compatible con el SDK de OpenAI —
# solo cambia la base_url y el api_key
client = AsyncOpenAI(
    api_key=os.getenv("DEEPINFRA_API_KEY"),
    base_url="https://api.deepinfra.com/v1/openai",
)

MODEL = "Qwen/Qwen3.5-9B"

async def chat_stream(messages: list[dict], thinking: bool = False):
    stream = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=512,
        temperature=0.7,
        top_p=0.8,
        presence_penalty=1.5,
        stream=True,
        extra_body={
            "top_k": 20,
            "chat_template_kwargs": {"enable_thinking": thinking},
        }
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
            
async def chat(messages: list[dict], max_tokens: int = 512, thinking: bool = False) -> dict:
    """
    Llama a DeepInfra vía SDK OpenAI-compatible.
    Retorna el mensaje del assistant como dict.
    """
    response = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.7,
        top_p=0.8,
        presence_penalty=1.5,
        extra_body={
            "top_k": 20,
            "chat_template_kwargs": {"enable_thinking": thinking},
        }
    )
    usage = response.usage
    cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
    logger.info(f"tokens — prompt: {usage.prompt_tokens} | cached: {cached} | completion: {usage.completion_tokens} | total: {usage.total_tokens}")
    msg = response.choices[0].message
    return {
        "role": msg.role,
        "content": msg.content or "",
        "tool_calls": msg.tool_calls or [],
    }
