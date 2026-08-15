from typing import List, Optional, Dict
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from core.config import settings


class StoryOptionsSchema(BaseModel):
    text: str
    node_id: Optional[int] = None
    generation_status: Optional[str] = "pending"
    expansion_job_id: Optional[str] = None


class StoryNodeBase(BaseModel):
    content: str
    is_ending: bool = False
    is_winning_ending: bool = False


class CompleteStoryNodeResponse(StoryNodeBase):
    id: int
    options: List[StoryOptionsSchema] = Field(default_factory=list)

    class Config:
        from_attributes = True


class StoryBase(BaseModel):
    title: str
    session_id: Optional[str] = None

    class Config:
        from_attributes = True


class CreateStoryRequest(BaseModel):
    theme: str
    depth: Optional[int] = None

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Theme is required.")
        if len(cleaned) > 120:
            raise ValueError("Theme must be 120 characters or fewer.")
        return cleaned

    @field_validator("depth")
    @classmethod
    def validate_depth(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return value
        if value < 3 or value > settings.MAX_STORY_DEPTH:
            raise ValueError(f"Depth must be between 3 and {settings.MAX_STORY_DEPTH}.")
        return value


class CompleteStoryResponse(StoryBase):
    id: int
    created_at: datetime
    root_node: CompleteStoryNodeResponse
    all_nodes: Dict[int, CompleteStoryNodeResponse]

    class Config:
        from_attributes = True


class ExpandOptionRequest(BaseModel):
    prefetch: bool = False


class ExpandOptionResponse(BaseModel):
    status: str
    job_id: Optional[str] = None
    story_id: int
    node_id: Optional[int] = None
