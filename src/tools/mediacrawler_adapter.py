import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from src.config import settings
from src.models.schemas import Comment, Post, SearchResult
from src.tools.adapter import CrawlerAdapter

# 我方平台名 → MediaCrawler CLI 代码
PLATFORM_MAP = {
    "xhs": "xhs",
    "douyin": "dy",
    "kuaishou": "ks",
    "bilibili": "bili",
    "weibo": "wb",
    "tieba": "tieba",
    "zhihu": "zhihu",
}
# MediaCrawler CLI 代码 → 存储目录名（各平台命名不一致，实测确认）
STORE_DIR_MAP = {
    "xhs": "xhs",
    "dy": "douyin",
    "ks": "kuaishou",
    "bili": "bili",
    "wb": "weibo",
    "tieba": "tieba",
    "zhihu": "zhihu",
}

# MediaCrawler CLI 代码 → 专属 CDP 调试端口（多平台并行采集时预分配，避免端口竞态）
CDP_PORT_MAP = {
    "xhs": 9222,
    "dy": 9223,
    "ks": 9224,
    "bili": 9225,
    "wb": 9226,
    "tieba": 9227,
    "zhihu": 9228,
}

# 各平台内容字段可能的 jsonl key（按优先级尝试）
_POST_ID_KEYS = ("note_id", "aweme_id", "video_id", "content_id", "mid")
_TITLE_KEYS = ("title", "content", "text", "name")
_CONTENT_KEYS = ("desc", "content", "text", "excerpt", "title")
_AUTHOR_KEYS = ("nickname", "user_name", "author")
_TIME_KEYS = ("time", "create_time", "publish_time", "pubdate")
_LIKE_KEYS = ("liked_count", "like_count", "digg_count", "attitudes_count")
_COMMENT_COUNT_KEYS = ("comment_count", "comments_count", "video_comment", "reply_count")
_COLLECT_KEYS = ("collected_count", "collect_count", "video_favorite_count", "favorite_count")
_URL_KEYS = ("note_url", "aweme_url", "video_url", "content_url", "detail_url")
_TYPE_KEYS = ("type", "aweme_type", "video_type")
_IMAGE_KEYS = ("image_list", "cover_url", "video_cover_url", "pic", "img_urls")
_COMMENT_LIKE_KEYS = ("like_count", "liked_count", "comment_like_count", "digg_count")
_COMMENT_POST_ID_KEYS = ("note_id", "aweme_id", "video_id", "content_id", "mid")


def _get(obj: dict, *keys, default=""):
    for k in keys:
        v = obj.get(k)
        if v not in (None, ""):
            return v
    return default


def _is_video_type(obj: dict) -> bool:
    t = str(_get(obj, *_TYPE_KEYS, default="")).lower()
    return t in ("video", "0")  # xhs "video"，抖音 "0" 为视频


def _parse_count(value) -> int:
    """解析计数字段，兼容 '10万+'、'4.5万'、'1.2亿'、'4970' 等格式。"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace(",", "")
    if not s:
        return 0
    factor = 1
    for unit, mul in (("亿", 1e8), ("万", 1e4), ("w", 1e4), ("W", 1e4), ("k", 1e3), ("K", 1e3)):
        if unit in s:
            factor = mul
            s = s.replace(unit, "")
            break
    s = s.replace("+", "").strip()
    try:
        return int(float(s) * factor)
    except ValueError:
        return 0


def _fmt_ts(value) -> str:
    if not value:
        return ""
    try:
        ts = int(value)
        if ts > 1e12:  # 毫秒时间戳
            ts //= 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def _extract_image_urls(obj: dict) -> list[str]:
    """从任意平台的 jsonl 提取图片 URL 列表。"""
    for key in _IMAGE_KEYS:
        raw = obj.get(key)
        if isinstance(raw, str):
            if raw.startswith("["):
                try:
                    items = json.loads(raw)
                    urls = [u for u in items if isinstance(u, str) and u.startswith("http")]
                    if urls:
                        return urls
                except json.JSONDecodeError:
                    pass
            elif raw.startswith("http"):
                return [raw]
        elif isinstance(raw, list):
            urls = [u for u in raw if isinstance(u, str) and u.startswith("http")]
            if urls:
                return urls
    return []


class MediaCrawlerAdapter(CrawlerAdapter):
    """封装 MediaCrawler（subprocess 方式，不改其源码）。"""

    def __init__(self, mc_dir: Path | None = None, raw_dir: Path | None = None):
        self.mc_dir = Path(mc_dir) if mc_dir else settings.mediacrawler_dir
        self.raw_dir = Path(raw_dir) if raw_dir else settings.raw_dir

    def search(
        self,
        platform: str,
        keyword: str,
        limit: int = 20,
        image_only: bool = False,
        log_cb=None,
        comments_limit: int = 10,
        sort_type: str | None = None,
    ) -> SearchResult:
        mc_platform = PLATFORM_MAP.get(platform, platform)
        # 每次采集写入独立运行目录，避免跨任务/跨主题数据串染
        run_dir = (
            self.raw_dir / "runs" / f"{mc_platform}_{datetime.now():%Y%m%d_%H%M%S_%f}"
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._run_search(mc_platform, keyword, limit, run_dir, log_cb=log_cb,
                             comments_limit=comments_limit, sort_type=sort_type)
        except RuntimeError as e:
            # 单平台失败不炸全局：降级为空结果，交给评估节点反馈 Planner 重规划
            import logging
            logging.getLogger(__name__).warning("平台 %s 采集失败: %s", mc_platform, str(e)[:200])
            if log_cb:
                log_cb(f"采集失败：{str(e)[:80]}")
            (run_dir / "error.txt").write_text(str(e), encoding="utf-8")

        (run_dir / "run_info.json").write_text(
            json.dumps(
                {"platform": mc_platform, "keywords": keyword.split(","), "limit": limit},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        posts = self._read_contents(mc_platform, keyword, run_dir, image_only=image_only)
        posts = self._truncate_posts(posts, mc_platform, limit)
        comments = self._read_comments(mc_platform, run_dir)
        comments = self._truncate_comments(comments, mc_platform, limit, comments_limit)
        return SearchResult(
            platform=platform, keyword=keyword, posts=posts, comments=comments
        )

    @staticmethod
    def _truncate_posts(posts: list[Post], mc_platform: str, limit: int) -> list[Post]:
        """精确截断：MediaCrawler 按页取整会多抓，这里严格裁到用户设置量。"""
        return posts[:limit] if len(posts) > limit else posts

    @staticmethod
    def _truncate_comments(
        comments: list[Comment], mc_platform: str, post_limit: int, comments_limit: int
    ) -> list[Comment]:
        """评论截断：每帖最多 comments_limit 条；知乎不尊重 max_count，在此统一兜底。"""
        per_post: dict[str, int] = {}
        result: list[Comment] = []
        for c in comments:
            pid = c.post_id or "_"
            n = per_post.get(pid, 0)
            if n >= comments_limit:
                continue
            per_post[pid] = n + 1
            result.append(c)
        return result

    def latest_run(self, mc_platform: str) -> Path | None:
        """该平台最近一次成功采集的运行目录（演示模式复放用）。"""
        runs_root = self.raw_dir / "runs"
        if not runs_root.is_dir():
            return None
        runs = sorted(runs_root.glob(f"{mc_platform}_*"), key=lambda p: p.name)
        valid = [r for r in runs if (r / "run_info.json").exists()]
        return valid[-1] if valid else None

    def check_session(self, platform: str) -> bool:
        return self.mc_dir.is_dir() and (self.mc_dir / "main.py").exists()

    def _run_search(
        self, mc_platform: str, keyword: str, limit: int, out_dir: Path, log_cb=None,
        comments_limit: int = 10, sort_type: str | None = None,
    ) -> None:
        cmd = [
            sys.executable, "main.py",
            "--platform", mc_platform,
            "--type", "search",
            "--keywords", keyword,
            "--get_comment", "true",
            "--save_data_option", "jsonl",
            "--save_data_path", str(out_dir),
            "--crawler_max_notes_count", str(int(limit)),
            "--max_comments_count_singlenotes", str(int(comments_limit)),
        ]
        # Popen 逐行读取子进程输出：实时解析采集进度 + 保留完整日志用于错误诊断
        env = os.environ.copy()
        env["MC_CDP_PORT"] = str(CDP_PORT_MAP.get(mc_platform, 9222))
        if sort_type:
            env["MC_XHS_SORT_TYPE"] = sort_type
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.mc_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        log_lines: list[str] = []
        note_count = 0
        for line in proc.stdout:  # type: ignore[union-attr]
            log_lines.append(line)
            if log_cb is None:
                continue
            try:
                if "Current search keyword:" in line:
                    kw = line.split("Current search keyword:", 1)[1].strip()
                    log_cb(f"搜索关键词「{kw}」")
                elif "Begin get note detail" in line:
                    note_count += 1
                    log_cb(f"已抓取 {note_count} 篇帖子详情")
                elif "fetching comments for note" in line:
                    log_cb(f"正在抓第 {note_count} 篇帖子的评论")
                elif "Crawler finished" in line:
                    log_cb("平台采集完成")
            except Exception:
                pass
        proc.wait()
        if proc.returncode != 0:
            err = "\n".join(log_lines[-60:])
            if any(k in err for k in ("CAPTCHA", "验证码", "风控", "461")):
                raise RuntimeError(
                    f"[{mc_platform}] 触发平台验证码/风控。建议：等几分钟后再试，"
                    "或在弹出的浏览器里手动完成验证码后重试。演示模式不受影响。"
                )
            raise RuntimeError(
                f"MediaCrawler 采集失败 (exit {proc.returncode}):\n{err[-2000:]}"
            )

    def _read_contents(
        self, mc_platform: str, keyword: str, out_dir: Path, image_only: bool = False
    ) -> list[Post]:
        store_dir = STORE_DIR_MAP.get(mc_platform, mc_platform)
        files = sorted((out_dir / store_dir / "jsonl").glob("search_contents_*.jsonl"))
        posts: list[Post] = []
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                obj = json.loads(line)
                if image_only and _is_video_type(obj):
                    continue
                posts.append(
                    Post(
                        platform=mc_platform,
                        post_id=str(_get(obj, *_POST_ID_KEYS)),
                        title=_get(obj, *_TITLE_KEYS),
                        content=_get(obj, *_CONTENT_KEYS),
                        author=_get(obj, *_AUTHOR_KEYS),
                        publish_time=_fmt_ts(_get(obj, *_TIME_KEYS)),
                        like_count=_parse_count(_get(obj, *_LIKE_KEYS)),
                        comment_count=_parse_count(_get(obj, *_COMMENT_COUNT_KEYS)),
                        collect_count=_parse_count(_get(obj, *_COLLECT_KEYS)),
                        url=_get(obj, *_URL_KEYS),
                        keyword=obj.get("source_keyword", keyword),
                        type=str(_get(obj, *_TYPE_KEYS)),
                        image_urls=_extract_image_urls(obj),
                    )
                )
        return posts

    def _read_comments(self, mc_platform: str, out_dir: Path) -> list[Comment]:
        store_dir = STORE_DIR_MAP.get(mc_platform, mc_platform)
        files = sorted((out_dir / store_dir / "jsonl").glob("search_comments_*.jsonl"))
        comments: list[Comment] = []
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                obj = json.loads(line)
                comments.append(
                    Comment(
                        platform=mc_platform,
                        comment_id=str(obj.get("comment_id", "")),
                        post_id=str(_get(obj, *_COMMENT_POST_ID_KEYS)),
                        content=_get(obj, "content", "text"),
                        author=_get(obj, *_AUTHOR_KEYS),
                        like_count=_parse_count(_get(obj, *_COMMENT_LIKE_KEYS)),
                        publish_time=_fmt_ts(_get(obj, "create_time", "time")),
                    )
                )
        return comments
