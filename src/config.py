import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _parse_models() -> list[str]:
    raw = os.getenv("LLM_MODELS", "deepseek-v4-flash")
    return [m.strip() for m in raw.split(",") if m.strip()]


@dataclass
class Settings:
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_models: list[str] = field(default_factory=_parse_models)
    llm_vision_model: str = os.getenv("LLM_VISION_MODEL", "sensenova-6.8-flash-lite")
    llm_structured_model: str = os.getenv("LLM_STRUCTURED_MODEL", "sensenova-6.8-flash-lite")

    platforms: list[str] = field(
        default_factory=lambda: [
            "xhs", "douyin", "kuaishou", "bilibili", "weibo", "tieba", "zhihu"
        ]
    )

    data_dir: Path = PROJECT_ROOT / "data"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    report_dir: Path = PROJECT_ROOT / "data" / "reports"
    db_path: Path = PROJECT_ROOT / "data" / "agent.db"

    mediacrawler_dir: Path = PROJECT_ROOT / "vendor" / "MediaCrawler"

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir, self.report_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
