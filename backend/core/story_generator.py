from __future__ import annotations

from dataclasses import dataclass

from google import genai
from google.genai import types
from pydantic import ValidationError

from core.config import settings
from core.gemini_key_pool import (
    GeminiQuotaExhaustedError,
    extract_retry_after_seconds,
    gemini_key_pool,
    is_quota_error,
)
from core.models import StoryInitialBundleLLM, StoryNodeExpansionLLM, StoryRootExpansionLLM
from core.prompts import (
    build_branch_generation_prompt,
    build_initial_bundle_generation_prompt,
    build_json_repair_prompt,
    build_root_generation_prompt,
)


class StructuredGenerationError(Exception):
    def __init__(self, message: str, raw_response: str = "", repaired_response: str | None = None):
        super().__init__(message)
        self.raw_response = raw_response
        self.repaired_response = repaired_response


@dataclass
class StructuredGenerationResult:
    parsed: StoryInitialBundleLLM | StoryRootExpansionLLM | StoryNodeExpansionLLM
    raw_response: str
    repaired_response: str | None = None
    repair_attempts: int = 0


class StoryGenerator:

    @classmethod
    def _generate_content(cls, *, contents: str, config: types.GenerateContentConfig):
        last_quota_error: Exception | None = None

        for _ in range(len(settings.gemini_api_keys)):
            lease = gemini_key_pool.lease()
            client = genai.Client(api_key=lease.api_key)

            try:
                return client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                if not is_quota_error(e):
                    raise
                last_quota_error = e
                gemini_key_pool.cool_down(
                    lease.key_index,
                    extract_retry_after_seconds(e)
                )

        try:
            retry_after = extract_retry_after_seconds(last_quota_error) if last_quota_error else 60.0
        except Exception:
            retry_after = 60.0

        raise GeminiQuotaExhaustedError(retry_after) from last_quota_error

    @classmethod
    def generate_root(cls, theme: str, target_depth: int, branching_factor: int) -> StructuredGenerationResult:
        prompt = build_root_generation_prompt(
            theme=theme,
            target_depth=target_depth,
            branching_factor=branching_factor
        )
        result = cls._generate_structured(
            schema_model=StoryRootExpansionLLM,
            prompt=prompt,
            repair_label="root story payload"
        )
        cls._validate_root_payload(result.parsed, branching_factor)
        return result

    @classmethod
    def generate_initial_bundle(
        cls,
        theme: str,
        target_depth: int,
        branching_factor: int
    ) -> StructuredGenerationResult:
        prompt = build_initial_bundle_generation_prompt(
            theme=theme,
            target_depth=target_depth,
            branching_factor=branching_factor
        )
        result = cls._generate_structured(
            schema_model=StoryInitialBundleLLM,
            prompt=prompt,
            repair_label="initial playable story bundle",
            max_output_tokens=4096
        )
        cls._validate_initial_bundle_payload(result.parsed, target_depth, branching_factor)
        return result

    @classmethod
    def generate_branch(
        cls,
        theme: str,
        path_context: str,
        option_text: str,
        depth: int,
        target_depth: int,
        branching_factor: int
    ) -> StructuredGenerationResult:
        prompt = build_branch_generation_prompt(
            theme=theme,
            path_context=path_context,
            option_text=option_text,
            depth=depth,
            target_depth=target_depth,
            branching_factor=branching_factor
        )
        result = cls._generate_structured(
            schema_model=StoryNodeExpansionLLM,
            prompt=prompt,
            repair_label="branch story payload",
            max_output_tokens=2048
        )
        cls._validate_branch_payload(
            result.parsed,
            depth=depth,
            target_depth=target_depth,
            branching_factor=branching_factor
        )
        return result

    @classmethod
    def _generate_structured(
        cls,
        schema_model,
        prompt: str,
        repair_label: str,
        max_output_tokens: int = 4096
    ) -> StructuredGenerationResult:
        response = cls._generate_content(
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema_model,
                max_output_tokens=max_output_tokens,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.MEDIUM
                ),
            ),
        )

        raw_text = response.text or ""

        try:
            parsed = response.parsed
            if parsed is None:
                parsed = schema_model.model_validate_json(raw_text)
            return StructuredGenerationResult(parsed=parsed, raw_response=raw_text)
        except (ValidationError, ValueError) as initial_error:
            repaired_result = cls._repair_structured_output(
                schema_model=schema_model,
                raw_text=raw_text,
                repair_label=repair_label,
                original_prompt=prompt,
                max_output_tokens=max_output_tokens
            )
            if repaired_result is not None:
                repaired_model, repaired_text = repaired_result
                return StructuredGenerationResult(
                    parsed=repaired_model,
                    raw_response=raw_text,
                    repaired_response=repaired_text,
                    repair_attempts=1
                )

            raise StructuredGenerationError(
                message=str(initial_error),
                raw_response=raw_text
            ) from initial_error

    @classmethod
    def _repair_structured_output(
        cls,
        schema_model,
        raw_text: str,
        repair_label: str,
        original_prompt: str,
        max_output_tokens: int
    ):
        if not raw_text:
            return None

        repair_prompt = build_json_repair_prompt(
            label=repair_label,
            raw_text=raw_text,
            original_prompt=original_prompt
        )

        for _ in range(settings.STORY_REPAIR_RETRIES):
            repair_response = cls._generate_content(
                contents=repair_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema_model,
                    max_output_tokens=max_output_tokens,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=types.ThinkingLevel.MEDIUM
                    ),
                ),
            )

            repaired_text = repair_response.text or ""

            try:
                repaired_model = repair_response.parsed
                if repaired_model is None:
                    repaired_model = schema_model.model_validate_json(repaired_text)
                return repaired_model, repaired_text
            except (ValidationError, ValueError):
                continue

        return None

    @classmethod
    def _validate_root_payload(cls, payload: StoryRootExpansionLLM, branching_factor: int) -> None:
        if payload.rootNode.isEnding:
            raise ValueError("Root node must not be an ending.")
        if not payload.rootNode.options or len(payload.rootNode.options) != branching_factor:
            raise ValueError(f"Root node must contain exactly {branching_factor} options.")

    @classmethod
    def _validate_initial_bundle_payload(
        cls,
        payload: StoryInitialBundleLLM,
        target_depth: int,
        branching_factor: int
    ) -> None:
        if payload.rootNode.isEnding:
            raise ValueError("Root node must not be an ending.")
        if not payload.rootNode.options or len(payload.rootNode.options) != branching_factor:
            raise ValueError(f"Root node must contain exactly {branching_factor} options.")
        if not payload.childNodes or len(payload.childNodes) != branching_factor:
            raise ValueError(f"Initial bundle must contain exactly {branching_factor} child nodes.")

        expected_indexes = set(range(branching_factor))
        received_indexes = {child.optionIndex for child in payload.childNodes}
        if received_indexes != expected_indexes:
            raise ValueError("Initial bundle childNodes must map exactly to root option indexes.")

        for child in payload.childNodes:
            cls._validate_branch_payload(
                child.node,
                depth=2,
                target_depth=target_depth,
                branching_factor=branching_factor
            )

    @classmethod
    def _validate_branch_payload(
        cls,
        payload: StoryNodeExpansionLLM,
        depth: int,
        target_depth: int,
        branching_factor: int
    ) -> None:
        must_end = depth >= target_depth
        if must_end and not payload.isEnding:
            raise ValueError("This branch should end at the configured target depth.")
        if depth < settings.MIN_ENDING_DEPTH and payload.isEnding:
            raise ValueError(f"Branches must not end before depth {settings.MIN_ENDING_DEPTH}.")
        if payload.isEnding:
            if payload.options not in (None, []):
                raise ValueError("Ending nodes must not contain options.")
            return
        if not payload.options or len(payload.options) != branching_factor:
            raise ValueError(f"Non-ending nodes must contain exactly {branching_factor} options.")
