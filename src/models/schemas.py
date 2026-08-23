from __future__ import annotations

from pydantic import BaseModel, Field


class Post(BaseModel):
    platform: str = ""
    post_id: str = ""
    title: str = ""
    content: str = ""
    author: str = ""
    publish_time: str = ""
    like_count: int = 0
    comment_count: int = 0
    collect_count: int = 0
    url: str = ""
    keyword: str = ""
    type: str = ""  # normal=图文, video=视频
    image_urls: list[str] = Field(default_factory=list)


class Comment(BaseModel):
    platform: str = ""
    comment_id: str = ""
    post_id: str = ""
    content: str = ""
    author: str = ""
    like_count: int = 0
    publish_time: str = ""


class SearchResult(BaseModel):
    platform: str = ""
    keyword: str = ""
    posts: list[Post] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)


class SubQuestion(BaseModel):
    question: str
    keywords: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    sub_questions: list[SubQuestion] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    dimension: str
    conclusion: str
    sources: list[str] = Field(default_factory=list)


class Report(BaseModel):
    task_id: str = ""
    markdown: str = ""
    sources: list[str] = Field(default_factory=list)
