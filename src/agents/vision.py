from src.config import settings
from src.llm.client import chat_vision
from src.tools.mediacrawler_adapter import PLATFORM_MAP, MediaCrawlerAdapter

VISION_PROMPT = "这是一张关于「{topic}」的社媒帖子配图。请用一句话描述它的视觉内容（画面内容、美术风格、UI 等），不超过 40 字。"


def analyze_visual(platform: str, topic: str, top_n: int = 3) -> str:
    mc = PLATFORM_MAP.get(platform, platform)
    adapter = MediaCrawlerAdapter()
    posts = adapter._read_contents(mc, "", settings.raw_dir, image_only=(platform == "xhs"))
    posts_with_img = [p for p in posts if p.image_urls]
    posts_with_img.sort(key=lambda p: p.like_count, reverse=True)
    top = posts_with_img[:top_n]
    if not top:
        return ""
    lines = []
    for p in top:
        url = p.image_urls[0]
        try:
            desc = chat_vision(
                VISION_PROMPT.format(topic=topic), [url], temperature=0.2, max_tokens=2000
            ).strip()
            if desc:
                lines.append(f"- [{p.title[:20]}] {desc}")
        except Exception as e:
            lines.append(f"- [{p.title[:20]}] 图片分析失败({type(e).__name__})")
    return "\n".join(lines)
