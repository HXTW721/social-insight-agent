import json
import threading

from openai import OpenAI

from src.config import settings

_client: OpenAI | None = None
_client_lock = threading.Lock()
_idx = 0
_idx_lock = threading.Lock()


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    return _client


def _next_start() -> int:
    """轮询：每次调用从下一个模型开始。"""
    global _idx
    with _idx_lock:
        start = _idx
        _idx = (_idx + 1) % len(settings.llm_models)
        return start


def _complete(
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    model: str,
    response_format: dict | None = None,
) -> str:
    client = get_client()
    kwargs = dict(
        model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    if response_format is not None:
        kwargs["response_format"] = response_format
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def chat(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 4000,
    model: str | None = None,
    response_format: dict | None = None,
) -> str:
    """轮询 + 失败兜底：从轮询起点逐个尝试，全部失败才抛异常。"""
    models = [model] if model else settings.llm_models
    start = _next_start() % len(models)
    last_err: Exception | None = None
    for i in range(len(models)):
        m = models[(start + i) % len(models)]
        try:
            return _complete(messages, temperature, max_tokens, m, response_format)
        except Exception as e:
            last_err = e
    assert last_err is not None
    raise last_err


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return text


def chat_json(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 8000,
    model: str | None = None,
) -> dict:
    rf = {"type": "json_object"}
    text = chat(messages, temperature=temperature, max_tokens=max_tokens, model=model, response_format=rf)
    try:
        return json.loads(_strip_json(text))
    except (json.JSONDecodeError, ValueError):
        retry = messages + [
            {"role": "user", "content": "请只输出一个合法 JSON 对象，不要任何额外文字、解释或代码块。"}
        ]
        text2 = chat(retry, temperature=0.0, max_tokens=max_tokens, model=model, response_format=rf)
        return json.loads(_strip_json(text2))


def chat_structured(
    messages: list[dict],
    schema: dict,
    temperature: float = 0.2,
    max_tokens: int = 8000,
    model: str | None = None,
) -> dict:
    """结构化输出：用 tool-calling 强制模型返回符合 schema 的 JSON（比 json_object 更稳）。"""
    m = model or settings.llm_structured_model
    tool = {
        "type": "function",
        "function": {"name": "submit", "description": "提交结构化结果", "parameters": schema},
    }
    try:
        resp = get_client().chat.completions.create(
            model=m,
            messages=messages,
            tools=[tool],
            tool_choice="required",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            raise ValueError("模型未调用工具，无法获取结构化输出")
        return json.loads(msg.tool_calls[0].function.arguments)
    except Exception:
        return chat_json(messages, temperature=temperature, max_tokens=max_tokens, model=m)


def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 4000,
    model: str | None = None,
):
    """带工具调用的对话，轮询 + 兜底，返回 assistant message（含 tool_calls 或 content）。"""
    models = [model] if model else settings.llm_models
    start = _next_start() % len(models)
    last_err: Exception | None = None
    for i in range(len(models)):
        m = models[(start + i) % len(models)]
        try:
            resp = get_client().chat.completions.create(
                model=m,
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message
        except Exception as e:
            last_err = e
    assert last_err is not None
    raise last_err


def chat_vision(
    text: str,
    image_urls: list[str],
    temperature: float = 0.3,
    max_tokens: int = 2000,
) -> str:
    """多模态识图，走 vision 模型（默认 sensenova-6.8-flash-lite）。"""
    content: list[dict] = [{"type": "text", "text": text}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    messages = [{"role": "user", "content": content}]
    return chat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        model=settings.llm_vision_model,
    )
