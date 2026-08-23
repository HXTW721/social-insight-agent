import argparse

from src.storage.db import DB
from src.tools.mediacrawler_adapter import MediaCrawlerAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description="采集社媒图文+评论并落库")
    parser.add_argument("--platform", default="xhs", help="xhs | douyin")
    parser.add_argument("--keyword", required=True, help="搜索关键词")
    parser.add_argument("--limit", type=int, default=20, help="帖子/评论采集上限")
    args = parser.parse_args()

    adapter = MediaCrawlerAdapter()
    result = adapter.search(args.platform, args.keyword, args.limit)

    db = DB()
    for p in result.posts:
        db.upsert_post(p)
    for c in result.comments:
        db.upsert_comment(c)

    print(f"平台={args.platform} 关键词={args.keyword}")
    print(f"帖子={len(result.posts)} 评论={len(result.comments)}")
    print(f"库中累计 帖子={db.count_posts()} 评论={db.count_comments()}")
    db.close()


if __name__ == "__main__":
    main()
