import streamlit as st

from src.agents.search_agent import _format_result, default_search
from src.config import settings
from src.models.schemas import SearchResult
from src.orchestration.graph import build_graph
from src.tools.mediacrawler_adapter import PLATFORM_MAP, MediaCrawlerAdapter

st.set_page_config(
    page_title="社媒行情洞察 Agent",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'Fira Sans', sans-serif; }
  .agent-header { padding: 0.5rem 0 1rem 0; border-bottom: 1px solid #334155; margin-bottom: 1.2rem; }
  .agent-header h1 { font-size: 1.9rem; font-weight: 700; color: #E2E8F0; margin: 0; }
  .agent-header .sub { color: #94A3B8; font-size: 0.95rem; margin-top: 0.2rem; }
  .step-card {
    background: #1E293B; border: 1px solid #334155; border-radius: 10px;
    padding: 1rem 0.9rem; min-height: 92px;
  }
  .step-card.done { border-color: #3B82F6; background: #17243B; }
  .step-card.running { border-color: #D97706; background: #2A2118; }
  .step-num { font-size: 0.75rem; color: #64748B; font-family: 'Fira Code', monospace; }
  .step-name { font-size: 0.95rem; font-weight: 600; color: #E2E8F0; margin-top: 0.2rem; }
  .step-status { font-size: 0.8rem; margin-top: 0.4rem; }
  .step-status.done { color: #34D399; }
  .step-status.running { color: #D97706; animation: pulse 1.2s ease-in-out infinite; }
  .step-status.pending { color: #64748B; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
</style>
""",
    unsafe_allow_html=True,
)


def _make_search_func(mode: str):
    if mode.startswith("演示"):
        adapter = MediaCrawlerAdapter()

        def mock(platform, keyword, limit=10, image_only=False, topic="", log_cb=None):
            mc = PLATFORM_MAP.get(platform, platform)
            run_dir = adapter.latest_run(mc)
            if run_dir is None:
                return f"平台={platform} 无已采集数据（该平台还没有成功采集过）"
            posts = adapter._read_contents(mc, keyword, run_dir, image_only=image_only)
            comments = adapter._read_comments(mc, run_dir)
            r = SearchResult(platform=platform, keyword=keyword, posts=posts, comments=comments)
            return _format_result(r)

        return mock
    return default_search


STEPS = ["Planner 规划", "Researcher 采集", "Analyst 分析", "Vision 识图", "Reporter 报告"]
RUNNING_GIF = '<span class="spinner">⏳</span>'


def render_pipeline(done_steps: set[str], running_step: str | None = None):
    cols = st.columns(5)
    for col, step in zip(cols, STEPS):
        if step in done_steps:
            cls, status = "done", "✓ 完成"
        elif step == running_step:
            cls, status = "running", "⏳ 执行中"
        else:
            cls, status = "pending", "待执行"
        with col:
            st.markdown(
                f"""
<div class="step-card {cls}">
  <div class="step-num">STEP {STEPS.index(step) + 1}</div>
  <div class="step-name">{step}</div>
  <div class="step-status {cls}">{status}</div>
</div>
""",
                unsafe_allow_html=True,
            )


# 头部
st.markdown(
    """
<div class="agent-header">
  <h1>社媒行情洞察 Agent</h1>
  <div class="sub">多 Agent 协作 · Planner → Researcher → Analyst → Reporter · 基于真实社媒图文+评论</div>
</div>
""",
    unsafe_allow_html=True,
)

# 平台采集特性：页大小（MediaCrawler 按页抓取）+ 特有参数
PLATFORM_META = {
    "xhs":      {"label": "小红书", "page_size": 20, "sort": True},
    "douyin":   {"label": "抖音",   "page_size": 10, "publish_time": True},
    "ks":       {"label": "快手",   "page_size": 20},
    "bilibili": {"label": "B站",    "page_size": 20},
    "wb":       {"label": "微博",   "page_size": 10, "search_type": True},
    "tieba":    {"label": "贴吧",   "page_size": 10},
    "zhihu":    {"label": "知乎",   "page_size": 20},
}

# 研究进行中标记：点击开始后置 True，结束后清除（用于禁用侧边栏交互）
if "researching" not in st.session_state:
    st.session_state.researching = False

# 侧边栏：平台卡片（点击展开选择参数，勾选 = 启用该平台）
with st.sidebar:
    st.header("平台配置")
    if st.session_state.researching:
        st.info("⏳ 研究进行中，配置已锁定")
    st.caption("勾选启用平台；每个平台按「页」采集，页大小由平台决定。")
    mode = st.radio(
        "采集模式", ["演示（复用已采集数据）", "真实采集"], index=0,
        disabled=st.session_state.researching,
    )
    comments_per_post = st.slider(
        "每篇帖子评论数", 1, 30, 10, step=1,
        disabled=st.session_state.researching,
    )
    image_only = st.checkbox(
        "只抓图文（过滤视频）", value=True,
        disabled=st.session_state.researching,
    )
    st.divider()

platforms: list[str] = []
per_platform_pages: dict[str, int] = {}
per_platform_sort: dict[str, str] = {}
per_platform_max_keywords: dict[str, int] = {}
for pcode, meta in PLATFORM_META.items():
    with st.sidebar.expander(f"{meta['label']} ({pcode})", expanded=False):
        enabled = st.checkbox(
            "启用", key=f"en_{pcode}", value=(pcode == "xhs"),
            disabled=st.session_state.researching,
        )
        if enabled:
            platforms.append(pcode)
        pages = st.slider(
            f"爬几页（每页{meta['page_size']}条）", 1, 5, 1, step=1, key=f"pg_{pcode}",
            help="实际采集量 ≈ 页数 × 每页条数 × 关键词数",
            disabled=st.session_state.researching,
        )
        per_platform_pages[pcode] = pages
        per_platform_max_keywords[pcode] = st.slider(
            "最多使用关键词数", 1, 10, 3, step=1, key=f"kw_{pcode}",
            help="限制该平台实际用于搜索的关键词个数",
            disabled=st.session_state.researching,
        )
        if meta.get("sort"):
            per_platform_sort[pcode] = st.selectbox(
                "排序", ["popularity_descending", "time_descending", "general"],
                format_func=lambda s: {"popularity_descending": "热门优先", "time_descending": "最新优先", "general": "综合"}.get(s, s),
                key=f"sort_{pcode}",
                disabled=st.session_state.researching,
            )

st.sidebar.divider()
st.sidebar.caption("演示模式秒出结果；真实采集会启动浏览器并联网抓取，较慢（约数分钟）。")

# 全局 limit：取所有启用平台的 页数×页大小 的最大值（MediaCrawler 用单一总量参数）
depth = max((per_platform_pages[p] * PLATFORM_META[p]["page_size"] for p in platforms), default=20)

# 输入区
col1, col2 = st.columns([4, 1])
with col1:
    topic = st.text_input(
        "研究主题", value="独立游戏市场行情",
        placeholder="例如：独立游戏市场行情、肉鸽游戏玩法趋势",
        disabled=st.session_state.researching,
    )
with col2:
    st.write("")
    start = st.button(
        "开始研究", type="primary", use_container_width=True,
        disabled=st.session_state.researching,
    )

st.divider()

st.subheader("执行流水线")
pipeline_placeholder = st.empty()
with pipeline_placeholder.container():
    render_pipeline(set())

result_placeholder = st.empty()

if start:
    if not topic:
        st.warning("请输入研究主题")
    else:
        st.session_state.researching = True
        search_func = _make_search_func(mode)
        final_state = None
        try:
            graph = build_graph(
                search_func, limit=depth, image_only=image_only,
                platforms=platforms, comments_limit=comments_per_post,
                per_platform_pages=per_platform_pages,
                per_platform_max_keywords=per_platform_max_keywords,
                per_platform_sort=per_platform_sort or None,
            )
            step_order = ["Planner 规划", "Researcher 采集", "Analyst 分析", "Vision 识图", "Reporter 报告"]
            for state in graph.stream({"topic": topic}, stream_mode="values"):
                final_state = state
                done_steps: set[str] = set()
                if "plan" in state:
                    done_steps.add("Planner 规划")
                if "data" in state:
                    done_steps.add("Researcher 采集")
                if state.get("analyses"):
                    done_steps.add("Analyst 分析")
                if "visual_insight" in state:
                    done_steps.add("Vision 识图")
                if "report" in state:
                    done_steps.add("Reporter 报告")
                running_step = next((s for s in step_order if s not in done_steps), None)
                with pipeline_placeholder.container():
                    render_pipeline(done_steps, running_step)
            with pipeline_placeholder.container():
                render_pipeline(set(step_order))
        except Exception:
            st.session_state.researching = False
            raise
        # 研究正常结束，解锁侧边栏
        st.session_state.researching = False

        with result_placeholder.container():
            st.divider()
            st.subheader("研究报告")
            with st.expander("查看中间结果（计划 / 采集 / 分析 / 识图）", expanded=False):
                st.json({"plan": final_state.get("plan", {})}, expanded=False)
                st.markdown(f"**采集数据块**：{len(final_state.get('data', []))} 块")
                for a in final_state.get("analyses", []):
                    st.markdown(f"**{a['dimension']}**：{a['conclusion'][:200]}…")
                if final_state.get("visual_insight"):
                    st.markdown("**视觉/美术风格分析**：")
                    st.markdown(final_state["visual_insight"])
            st.markdown(final_state.get("report", ""))
