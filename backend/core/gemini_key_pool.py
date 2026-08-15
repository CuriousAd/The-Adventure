from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

from core.config import settings


class GeminiQuotaExhaustedError(Exception):
    def __init__(self, retry_after_seconds: float):
        super().__init__(f"All Gemini API keys are temporarily rate limited. Retry after {retry_after_seconds:.1f}s.")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class GeminiKeyLease:
    api_key: str
    key_index: int


class GeminiKeyPool:
    def __init__(self):
        self._lock = threading.Lock()
        self._next_index = 0
        self._cooldowns: dict[int, float] = {}

    def lease(self) -> GeminiKeyLease:
        keys = settings.gemini_api_keys
        now = time.monotonic()

        with self._lock:
            available_indexes = [
                index
                for index in range(len(keys))
                if self._cooldowns.get(index, 0) <= now
            ]

            if not available_indexes:
                retry_after = min(self._cooldowns.values()) - now
                raise GeminiQuotaExhaustedError(max(retry_after, 1.0))

            for offset in range(len(keys)):
                index = (self._next_index + offset) % len(keys)
                if index in available_indexes:
                    self._next_index = (index + 1) % len(keys)
                    return GeminiKeyLease(api_key=keys[index], key_index=index)

            index = available_indexes[0]
            self._next_index = (index + 1) % len(keys)
            return GeminiKeyLease(api_key=keys[index], key_index=index)

    def cool_down(self, key_index: int, retry_after_seconds: float) -> None:
        with self._lock:
            self._cooldowns[key_index] = time.monotonic() + max(retry_after_seconds, 1.0)


def is_quota_error(error: Exception) -> bool:
    text = str(error)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower()


def extract_retry_after_seconds(error: Exception) -> float:
    text = str(error)

    retry_delay_match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", text)
    if retry_delay_match:
        return float(retry_delay_match.group(1))

    retry_in_match = re.search(r"retry in (\d+(?:\.\d+)?)s", text, re.IGNORECASE)
    if retry_in_match:
        return float(retry_in_match.group(1))

    return 60.0


gemini_key_pool = GeminiKeyPool()
