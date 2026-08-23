from concurrent.futures import ThreadPoolExecutor
from operator import add
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.agents.analyst import analyze
from src.agents.planner import plan, replan
from src.agents.reporter import report
from src.agents.search_agent import default_search
from src.agents.vision import analyze_visual
from src.config import settings

DIMENSIONS = ["市场热度", "玩家/用户真实声音", "痛点与机会", "竞品与题材"]
MAX_REPLANS = 1  # 每轮采集最多反馈给规划者重规划一次


class ResearchState(TypedDict, total=False):
    topic: str
    plan: dict
    replan_count: int
    replan_feedback: dict
    eval_total_posts: int
    data: list[str]
    dimension: str
    data_text: str
    analyses: Annotated[list[dict], add]
    visual_insight: str
    report: str


def _build_plan_node(platforms: list[str]):
    def _plan_node(state: ResearchState) -> dict:
        return {"plan": plan(state["topic"], platforms=platforms), "replan_count": 0}
    return _plan_node


def _extract_keywords_by_platform(plan_dict: dict, platforms: list[str], max_keywords: dict | None = None) -> dict[str, str]:
    """从计划中提取每个平台自己的关键词串（跨子问题去重保序，尊重每平台上限）。"""
    result: dict[str, list[str]] = {p: [] for p in platforms}
    for sq in plan_dict.get("sub_questions", []):
        kbp = sq.get("keywords_by_platform", {})
        if isinstance(kbp, str):  # 模型偶发返回字符串，兜底成所有平台共用
            kbp = {p: kbp.replace("，", ",").split(",") for p in platforms}
        for p in platforms:
            kws = kbp.get(p, [])
            if isinstance(kws, str):
                kws = kws.replace("，", ",").split(",")
            result[p].extend(kws[:1])  # 每个子问题每平台取 1 个
    return {
        p: ",".join(
            k.strip() for k in list(dict.fromkeys(kws))[: (max_keywords or {}).get(p, 10)]
            if k and k.strip()
        )
        for p, kws in result.items()
    }


def _build_research_node(search_func, limit: int, image_only: bool, platforms: list[str], progress_cb=None, comments_limit: int = 10, per_platform_pages: dict | None = None, per_platform_max_keywords: dict | None = None, per_platform_sort: dict | None = None):
    def _research_node(state: ResearchState) -> dict:
        keywords_by_platform = _extract_keywords_by_platform(state["plan"], platforms, per_platform_max_keywords)

        def platform_label(p: str) -> str:
            return {"xhs": "小红书", "douyin": "抖音", "ks": "快手", "bili": "B站",
                    "wb": "微博", "tieba": "贴吧", "zhihu": "知乎"}.get(p, p)

        def crawl(platform: str) -> str:
            keyword_str = keywords_by_platform.get(platform, "")
            if not keyword_str:
                keyword_str = _extract_keywords_by_platform(state["plan"], platforms, per_platform_max_keywords).get(platform, "")
            if progress_cb:
                progress_cb("start", platform_label(platform), "")
            # 平台专属页数：页数 × 该平台页大小；未配置则用全局 limit
            platform_limit = limit
            if per_platform_pages and platform in per_platform_pages:
                page_size = {"xhs": 20, "douyin": 10, "ks": 20, "bilibili": 20,
                             "wb": 10, "tieba": 10, "zhihu": 20}.get(platform, 20)
                platform_limit = per_platform_pages[platform] * page_size
            sort_type = (per_platform_sort or {}).get(platform)
            text = search_func(
                platform, keyword_str, limit=platform_limit, image_only=image_only,
                log_cb=(lambda msg, pl=platform: progress_cb("log", platform_label(pl), msg))
                if progress_cb else None,
                topic="",
                comments_limit=comments_limit,
                sort_type=sort_type,
            )
            if progress_cb:
                progress_cb("done", platform_label(platform), "")
            return f"【平台】{platform} 【关键词】{keyword_str}\n{text}"

        # 跨平台并行采集（单平台内 MediaCrawler 仍串行）
        if len(platforms) <= 1:
            data_blocks = [crawl(p) for p in platforms]
        else:
            with ThreadPoolExecutor(max_workers=len(platforms)) as ex:
                data_blocks = list(ex.map(crawl, platforms))
        return {"data": data_blocks}

    return _research_node


def _evaluate_node(state: ResearchState) -> dict:
    """质量评估：汇总各平台采集结果，判断是否有效、哪些平台失败（含失败时用的关键词）。"""
    total_posts = 0
    failed_platforms: list[str] = []
    failed_keywords: dict[str, str] = {}
    for block in state.get("data", []):
        lines = (block or "").split("\n")
        first_line = lines[0] if lines else ""
        # 首行格式：【平台】xxx 【关键词】kw1,kw2
        platform = first_line.replace("【平台】", "").split("【关键词】")[0].strip()
        used_keywords = first_line.split("【关键词】")[1].strip() if "【关键词】" in first_line else ""
        # 统计行在第二行，格式：平台=xxx 关键词=yyy: 帖子20篇, 评论90条
        stat_line = lines[1] if len(lines) > 1 else ""
        posts = 0
        if "帖子" in stat_line and "篇" in stat_line:
            seg = stat_line.split("帖子", 1)[1].split("篇", 1)[0]
            digits = "".join(ch for ch in seg if ch.isdigit())
            posts = int(digits) if digits else 0
        if posts == 0:
            failed_platforms.append(platform)
            failed_keywords[platform] = used_keywords
        total_posts += posts
    return {
        "replan_feedback": {
            "total_posts": total_posts,
            "failed_platforms": failed_platforms,
            "failed_keywords": failed_keywords,
        },
        "eval_total_posts": total_posts,
    }


def _after_evaluate(state: ResearchState):
    """有效 → 分析；无效且还有额度 → 重规划；重规划过仍无效 → 带空数据继续。"""
    if state.get("eval_total_posts", 0) > 0:
        return "dispatch"
    if state.get("replan_count", 0) < MAX_REPLANS:
        return "replanner"
    return "dispatch"


def _dispatch_node(state: ResearchState) -> dict:
    """空操作占位：统一从 evaluate 出来的入口（真实分发靠条件边到 analyze_dimension 的 Send）。"""
    return {}


def _build_replan_node(platforms: list[str] | None = None):
    def _replan_node(state: ResearchState) -> dict:
        feedback = state.get("replan_feedback", {})
        new_plan = replan(
            state["topic"], state["plan"],
            feedback.get("failed_platforms", []), feedback.get("total_posts", 0),
            platforms=platforms,
            failed_keywords=feedback.get("failed_keywords"),
        )
        return {"plan": new_plan, "replan_count": state.get("replan_count", 0) + 1}
    return _replan_node


def _dispatch_analysts(state: ResearchState):
    """fan-out：为每个维度派发一个并行分析任务。"""
    data_text = "\n\n".join(state["data"])[:6000]
    return [
        Send("analyze_dimension", {"dimension": dim, "data_text": data_text})
        for dim in DIMENSIONS
    ]


def _analyze_dimension(state: ResearchState) -> dict:
    result = analyze(state["dimension"], state["data_text"])
    return {"analyses": [result]}


def _build_vision_node(platforms: list[str]):
    def _vision_node(state: ResearchState) -> dict:
        insights = []
        for platform in platforms:
            insight = analyze_visual(platform, state["topic"])
            if insight:
                insights.append(f"【{platform}】\n{insight}")
        return {"visual_insight": "\n\n".join(insights)}

    return _vision_node


def _report_node(state: ResearchState) -> dict:
    return {
        "report": report(
            state["topic"], state["plan"], state["analyses"], state.get("visual_insight", "")
        )
    }


def build_graph(
    search_func=default_search,
    limit: int = 5,
    image_only: bool = True,
    platforms: list[str] | None = None,
    progress_cb=None,
    comments_limit: int = 10,
    per_platform_pages: dict | None = None,
    per_platform_max_keywords: dict | None = None,
    per_platform_sort: dict | None = None,
):
    platforms = platforms or settings.platforms
    g = StateGraph(ResearchState)
    g.add_node("planner", _build_plan_node(platforms))
    g.add_node("replanner", _build_replan_node(platforms))
    g.add_node(
        "researcher",
        _build_research_node(search_func, limit, image_only, platforms, progress_cb, comments_limit,
                             per_platform_pages, per_platform_max_keywords, per_platform_sort),
    )
    g.add_node("evaluate", _evaluate_node)
    g.add_node("dispatch", _dispatch_node)
    g.add_node("analyze_dimension", _analyze_dimension)
    g.add_node("vision", _build_vision_node(platforms))
    g.add_node("reporter", _report_node)
    g.add_edge(START, "planner")
    g.add_edge("planner", "researcher")
    g.add_edge("researcher", "evaluate")
    g.add_conditional_edges("evaluate", _after_evaluate, ["replanner", "dispatch"])
    g.add_edge("replanner", "researcher")
    g.add_conditional_edges("dispatch", _dispatch_analysts, ["analyze_dimension"])
    g.add_edge("analyze_dimension", "vision")
    g.add_edge("vision", "reporter")
    g.add_edge("reporter", END)
    return g.compile()


def run_research(
    topic: str,
    search_func=default_search,
    limit: int = 5,
    image_only: bool = True,
    platforms: list[str] | None = None,
    progress_cb=None,
) -> dict:
    graph = build_graph(
        search_func, limit=limit, image_only=image_only, platforms=platforms, progress_cb=progress_cb
    )
    return graph.invoke({"topic": topic})
