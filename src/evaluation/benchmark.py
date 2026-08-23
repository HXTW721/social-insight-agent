from src.agents.search_agent import SearchAgent, _format_result
from src.config import settings
from src.llm.client import chat_structured
from src.models.schemas import SearchResult
from src.orchestration.graph import run_research
from src.tools.mediacrawler_adapter import PLATFORM_MAP, MediaCrawlerAdapter

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "structure": {"type": "integer", "description": "结构清晰度 1-5"},
        "data_citation": {"type": "integer", "description": "数据引用充分度 1-5"},
        "insight_depth": {"type": "integer", "description": "洞察深度 1-5"},
        "source_integrity": {"type": "integer", "description": "来源完整性 1-5"},
        "overall": {"type": "integer", "description": "综合评分 1-5"},
    },
    "required": ["structure", "data_citation", "insight_depth", "source_integrity", "overall"],
}

DIMENSIONS = ["structure", "data_citation", "insight_depth", "source_integrity", "overall"]

TOPICS = ["独立游戏市场行情", "肉鸽游戏玩法趋势"]


def _make_mock_search():
    adapter = MediaCrawlerAdapter()

    def mock(platform, keyword, limit=10, image_only=False, topic="", log_cb=None):
        mc = PLATFORM_MAP.get(platform, platform)
        run_dir = adapter.latest_run(mc)
        if run_dir is None:
            return f"平台={platform} 无已采集数据"
        posts = adapter._read_contents(mc, keyword, run_dir, image_only=image_only)
        comments = adapter._read_comments(mc, run_dir)
        r = SearchResult(platform=platform, keyword=keyword, posts=posts, comments=comments)
        return _format_result(r)

    return mock


def judge(topic: str, report_text: str) -> dict:
    prompt = f"""你是评测裁判。给定研究主题和一份报告，从以下维度打分（1-5 整数）：
- structure: 结构是否清晰、分章节
- data_citation: 是否引用具体数据（点赞/评论数等）
- insight_depth: 洞察是否有深度、有可行动结论
- source_integrity: 来源是否真实完整（有链接）
- overall: 综合评分

研究主题：{topic}
报告：
{report_text[:6000]}
"""
    return chat_structured(
        [{"role": "user", "content": prompt}], JUDGE_SCHEMA, temperature=0.0, max_tokens=4000
    )


def run_benchmark(search_func=None) -> list[dict]:
    search_func = search_func or _make_mock_search()
    rows = []
    for topic in TOPICS:
        single_report = SearchAgent(search_func=search_func).run(topic)
        single_score = judge(topic, single_report)

        multi_report = run_research(topic, search_func=search_func)["report"]
        multi_score = judge(topic, multi_report)

        rows.append({"topic": topic, "single": single_score, "multi": multi_score})
    return rows


def _avg(scores: list[dict], dim: str) -> float:
    vals = [s[dim] for s in scores]
    return sum(vals) / len(vals) if vals else 0.0


def print_report(rows: list[dict]) -> None:
    single_scores = [r["single"] for r in rows]
    multi_scores = [r["multi"] for r in rows]
    print("\n=== 单 Agent vs 多 Agent 评测对比 ===\n")
    print(f"{'维度':<16}{'单 Agent':<12}{'多 Agent':<12}")
    print("-" * 40)
    for dim in DIMENSIONS:
        s = _avg(single_scores, dim)
        m = _avg(multi_scores, dim)
        print(f"{dim:<16}{s:<12.2f}{m:<12.2f}")
    print("-" * 40)
    s_overall = _avg(single_scores, "overall")
    m_overall = _avg(multi_scores, "overall")
    print(f"{'综合':<16}{s_overall:<12.2f}{m_overall:<12.2f}")
    print(f"\n提升: {(m_overall - s_overall) / s_overall * 100:.1f}%")


if __name__ == "__main__":
    rows = run_benchmark()
    print_report(rows)
