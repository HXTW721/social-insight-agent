import json
from datetime import date

from src.config import settings
from src.llm.client import chat_structured

PLATFORM_LABELS = {
    "xhs": "小红书", "douyin": "抖音", "ks": "快手", "bili": "B站",
    "wb": "微博", "tieba": "贴吧", "zhihu": "知乎",
}

PLANNER_PROMPT = """你是研究规划者（Planner）。给定一个研究主题和目标平台列表，请把主题拆解成 3~5 个子问题，覆盖这几个方面：市场热度、用户/玩家痛点、真实声音、竞品与机会。

并为每个子问题给出**每个平台各自**的 1~2 个搜索关键词。关键词要贴合平台内容风格：
- 小红书：口语化、带话题标签（如 #独立游戏、求推荐类）
- 抖音：短热词、情绪化表达
- B站：评测/教程类词汇（如 "开发教程"、"深度解析"）
- 知乎：问句式、行业分析类（如 "前景如何"、"现状怎样"）
- 快手：接地气的口语
- 微博：热点事件词
- 贴吧：社区黑话、具体游戏/品类名

涉及年份的关键词一律用 {today_year} 年（今年），不要用过时的年份。

目标平台：{platforms}"""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "keywords_by_platform": {
                        "type": "object",
                        "description": "键为平台代码，值为该平台的关键词数组",
                        "additionalProperties": {
                            "type": "array", "items": {"type": "string"}
                        },
                    },
                },
                "required": ["question", "keywords_by_platform"],
            },
        },
    },
    "required": ["sub_questions"],
}


def plan(topic: str, platforms: list[str] | None = None) -> dict:
    platforms = platforms or ["xhs"]
    today_year = date.today().year
    platform_names = "、".join(
        f"{PLATFORM_LABELS.get(p, p)}({p})" for p in platforms
    )
    messages = [
        {
            "role": "system",
            "content": PLANNER_PROMPT.format(today_year=today_year, platforms=platform_names),
        },
        {"role": "user", "content": f"研究主题：{topic}"},
    ]
    result = chat_structured(messages, PLAN_SCHEMA, temperature=0.3, max_tokens=8000)
    # 兜底：确保每个目标平台都有 key（模型可能漏掉个别平台）
    for sq in result.get("sub_questions", []):
        kbp = sq.setdefault("keywords_by_platform", {})
        for p in platforms:
            if p not in kbp or not isinstance(kbp.get(p), list):
                kbp[p] = []
    return result


REPLAN_PROMPT = """你是研究规划者（Planner）。上一轮按你制定的关键词采集，结果无效：
- 采集到 0 篇帖子的平台及其当时使用的关键词：
{failed_details}
- 全部平台共采集帖子数：{total_posts}

原研究计划（JSON）：
{old_plan}

请重新规划检索策略。要求：
- 针对每个失败平台，分析它当时的关键词为什么无效（太长/太生僻/不符合该平台内容风格等）
- 为失败平台换一批更口语化、更短、更符合该平台风格的关键词
- 未失败的平台的关键词保持不变
- 保持覆盖原来的子问题维度，且仍按平台分别给出关键词

只输出与原来相同结构的 JSON。"""


def replan(
    topic: str, old_plan: dict, failed_platforms: list[str], total_posts: int,
    platforms: list[str] | None = None, failed_keywords: dict[str, str] | None = None,
) -> dict:
    platforms = platforms or ["xhs"]
    today_year = date.today().year
    if failed_keywords:
        failed_details = "\n".join(
            f"- {PLATFORM_LABELS.get(p, p)}({p}): 「{kws}」"
            for p, kws in failed_keywords.items()
        )
    else:
        failed_details = "\n".join(
            f"- {PLATFORM_LABELS.get(p, p)}({p})" for p in failed_platforms
        )
    messages = [
        {
            "role": "system",
            "content": REPLAN_PROMPT.format(
                failed_details=failed_details,
                total_posts=total_posts,
                old_plan=json.dumps(old_plan, ensure_ascii=False),
                today_year=today_year,
            ),
        },
        {"role": "user", "content": f"研究主题：{topic}"},
    ]
    result = chat_structured(messages, PLAN_SCHEMA, temperature=0.4, max_tokens=8000)
    for sq in result.get("sub_questions", []):
        kbp = sq.setdefault("keywords_by_platform", {})
        for p in platforms:
            if p not in kbp or not isinstance(kbp.get(p), list):
                kbp[p] = []
    return result
