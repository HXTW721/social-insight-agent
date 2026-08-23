import json
import threading

from src.llm.client import chat, chat_with_tools
from src.models.schemas import SearchResult
from src.storage.db import DB
from src.tools.mediacrawler_adapter import MediaCrawlerAdapter

_db_lock = threading.Lock()

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search",
        "description": "搜索小红书(xhs)或抖音(douyin)的图文帖子和评论，用于了解某个话题的真实热度与用户声音。",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["xhs", "douyin"],
                    "description": "平台：xhs=小红书，douyin=抖音",
                },
                "keyword": {"type": "string", "description": "中文搜索关键词"},
                "limit": {"type": "integer", "description": "返回帖子数量，默认10"},
            },
            "required": ["platform", "keyword"],
        },
    },
}

SYSTEM_PROMPT = """你是一个社媒行情研究助手，可以使用 search 工具搜索小红书/抖音的图文帖子和评论。

工作流程：
1. 分析用户主题，提炼 2~4 个搜索关键词
2. 调用 search 工具搜索（可对多个平台/关键词多次搜索）
3. 综合搜索结果，给出一段带来源的总结

总结要求：给出市场热度、玩家/用户真实关注点，引用具体评论，并附上帖子链接作为来源。禁止编造搜索里没有的内容。"""


def _format_result(result: SearchResult, max_posts: int = 8, max_comments: int = 15) -> str:
    lines = [
        f"平台={result.platform} 关键词={result.keyword}: 帖子{len(result.posts)}篇, 评论{len(result.comments)}条"
    ]
    for p in result.posts[:max_posts]:
        lines.append(
            f"- [{p.title[:40]}] 赞{p.like_count} 评{p.comment_count} 藏{p.collect_count} {p.url}"
        )
    for c in result.comments[:max_comments]:
        # 评论正文可能包含被截断的 URL，去掉以免污染来源链接
        content = c.content.replace("http", "ｈｔｔｐ")[:60]
        lines.append(f"  · 评论: {content} (赞{c.like_count})")
    return "\n".join(lines)


def default_search(
    platform: str,
    keyword: str,
    limit: int = 10,
    image_only: bool = False,
    log_cb=None,
    topic: str = "",
    comments_limit: int = 10,
    sort_type: str | None = None,
) -> str:
    """纯执行采集，不做关键词决策——无效结果由编排层的评估节点反馈给 Planner 重规划。"""
    adapter = MediaCrawlerAdapter()
    result = adapter.search(
        platform, keyword, limit, image_only=image_only, log_cb=log_cb,
        comments_limit=comments_limit, sort_type=sort_type,
    )
    with _db_lock:
        db = DB()
        for p in result.posts:
            db.upsert_post(p)
        for c in result.comments:
            db.upsert_comment(c)
        db.close()
    return _format_result(result)


class SearchAgent:
    def __init__(self, search_func=default_search):
        self.search_func = search_func

    def run(self, topic: str, max_steps: int = 6) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"研究主题：{topic}"},
        ]
        for _ in range(max_steps):
            msg = chat_with_tools(messages, [SEARCH_TOOL], temperature=0.3, max_tokens=4000)
            if msg.tool_calls:
                messages.append(msg.model_dump())
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    platform = args.get("platform", "xhs")
                    keyword = args.get("keyword", "")
                    limit = int(args.get("limit", 10))
                    result = self.search_func(platform, keyword, limit)
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result}
                    )
            else:
                return msg.content or ""
        return "达到最大步数仍未完成"
