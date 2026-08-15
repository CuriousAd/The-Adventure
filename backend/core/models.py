from __future__ import annotations

import json
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


def _coerce_json_string(value):
    if not isinstance(value, str):
        return value

    cleaned = value.strip()
    if not cleaned:
        return value

    cleaned = cleaned.lstrip(": \n\t")
    if cleaned in {"null", "true", "false"}:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return value

    if cleaned[:1] not in {"[", "{"}:
        return value

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return value


class StoryOptionSeedLLM(BaseModel):
    text: str = Field(description="The text shown to the player for this choice.")


class StoryNodeExpansionLLM(BaseModel):
    content: str = Field(description="Narrative content for the current story node.")
    isEnding: bool = Field(description="Whether this node is an ending.")
    isWinningEnding: bool = Field(description="Whether this ending is a winning ending.")
    options: Optional[List[StoryOptionSeedLLM]] = Field(
        default=None,
        description="The next choices available from this node. Use null for ending nodes."
    )

    @field_validator("options", mode="before")
    @classmethod
    def parse_options(cls, value):
        return _coerce_json_string(value)


class StoryRootExpansionLLM(BaseModel):
    title: str = Field(description="A compelling title for the story.")
    rootNode: StoryNodeExpansionLLM = Field(description="The opening node for the story.")


class StoryInitialChildLLM(BaseModel):
    optionIndex: int = Field(description="The zero-based root option index this child node belongs to.")
    node: StoryNodeExpansionLLM = Field(description="The generated child node for that root option.")


class StoryInitialBundleLLM(BaseModel):
    title: str = Field(description="A compelling title for the story.")
    rootNode: StoryNodeExpansionLLM = Field(description="The opening node for the story.")
    childNodes: List[StoryInitialChildLLM] = Field(
        description="One generated child node for each root option, keyed by zero-based root option index."
    )
