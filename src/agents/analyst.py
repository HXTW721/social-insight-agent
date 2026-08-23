from src.llm.client import chat_structured

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "dimension": {"type": "string"},
        "conclusion": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["dimension", "conclusion", "sources"],
}


def analyze(dimension: str, data_text: str) -> dict:
    prompt = f"""你是数据分析师（Analyst），负责「{dimension}」维度的分析。

基于下面采集的社媒帖子+评论数据，给出该维度的分析结论。要求：
- 引用具体数据（点赞/评论数）和真实评论内容
- 不要编造数据里没有的内容
- sources 只能放数据里**帖子行末尾**的完整链接（形如 https://www.xxx.com/... 的帖子 URL），评论内容里出现的链接一律不要放进 sources，禁止编造链接
- 如果数据里没有任何帖子链接，sources 返回空数组

数据：
{data_text}
"""
    messages = [{"role": "user", "content": prompt}]
    result = chat_structured(messages, ANALYSIS_SCHEMA, temperature=0.3, max_tokens=8000)
    # 模型偶发漏字段：dimension 用传入值兜底；conclusion 缺失则重试一次
    result.setdefault("dimension", dimension)
    if not result.get("conclusion"):
        retry_prompt = prompt + "\n\n注意：必须给出 conclusion 字段的具体分析内容。"
        result = chat_structured(
            [{"role": "user", "content": retry_prompt}],
            ANALYSIS_SCHEMA, temperature=0.2, max_tokens=8000,
        )
        result.setdefault("dimension", dimension)
    result.setdefault("sources", [])
    return result
