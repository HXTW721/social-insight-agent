from abc import ABC, abstractmethod

from src.models.schemas import SearchResult


class CrawlerAdapter(ABC):
    """采集层统一接口。平台失效时可换实现（如 XHS-Downloader），不改上层。"""

    @abstractmethod
    def search(self, platform: str, keyword: str, limit: int = 20) -> SearchResult:
        """按关键词搜索图文帖子 + 评论。"""

    @abstractmethod
    def check_session(self, platform: str) -> bool:
        """校验平台登录态是否有效。"""
