import sqlite3
from pathlib import Path

from src.config import settings
from src.models.schemas import Post, Comment

SCHEMA = """
CREATE TABLE IF NOT EXISTS post (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    post_id TEXT NOT NULL,
    title TEXT DEFAULT '',
    content TEXT DEFAULT '',
    author TEXT DEFAULT '',
    publish_time TEXT DEFAULT '',
    like_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    collect_count INTEGER DEFAULT 0,
    url TEXT DEFAULT '',
    keyword TEXT DEFAULT '',
    UNIQUE(platform, post_id)
);

CREATE TABLE IF NOT EXISTS comment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    comment_id TEXT NOT NULL,
    post_id TEXT DEFAULT '',
    content TEXT DEFAULT '',
    author TEXT DEFAULT '',
    like_count INTEGER DEFAULT 0,
    publish_time TEXT DEFAULT '',
    UNIQUE(platform, comment_id)
);
"""


class DB:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else settings.db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_post(self, post: Post) -> bool:
        inserted = self.conn.execute(
            """
            INSERT OR IGNORE INTO post
            (platform, post_id, title, content, author, publish_time,
             like_count, comment_count, collect_count, url, keyword)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post.platform, post.post_id, post.title, post.content,
                post.author, post.publish_time, post.like_count,
                post.comment_count, post.collect_count, post.url, post.keyword,
            ),
        ).rowcount
        self.conn.commit()
        return inserted > 0

    def upsert_comment(self, comment: Comment) -> bool:
        inserted = self.conn.execute(
            """
            INSERT OR IGNORE INTO comment
            (platform, comment_id, post_id, content, author, like_count, publish_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                comment.platform, comment.comment_id, comment.post_id,
                comment.content, comment.author, comment.like_count,
                comment.publish_time,
            ),
        ).rowcount
        self.conn.commit()
        return inserted > 0

    def count_posts(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM post").fetchone()[0]

    def count_comments(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM comment").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
