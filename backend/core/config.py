from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator
import os

class Settings(BaseSettings):
    API_PREFIX: str = "/api"
    DEBUG: bool = False

    DATABASE_URL: Optional[str] = None

    ALLOWED_ORIGINS: str = ""

    GEMINI_API_KEYS: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    JOB_EXECUTION_MODE: str = "background"
    STORY_GENERATION_RETRIES: int = 2
    STORY_TASK_MAX_ATTEMPTS: int = 3
    STORY_REPAIR_RETRIES: int = 1
    STALE_JOB_TIMEOUT_SECONDS: int = 900
    DEFAULT_STORY_DEPTH: int = 8
    MAX_STORY_DEPTH: int = 8
    MIN_ENDING_DEPTH: int = 4
    DEFAULT_BRANCHING_FACTOR: int = 2
    LAZY_INITIAL_DEPTH: int = 2
    LAZY_PREFETCH_ENABLED: bool = True
    AWS_REGION: Optional[str] = None
    STORY_WORKFLOW_ARN: Optional[str] = None

    def __init__(self, **values):
        super().__init__(**values)
        if not self.DEBUG and not self.DATABASE_URL:
            db_user = os.getenv("DB_USER")
            db_password = os.getenv("DB_PASSWORD")
            db_host = os.getenv("DB_HOST")
            db_port = os.getenv("DB_PORT")
            db_name = os.getenv("DB_NAME")
            missing = [
                key
                for key, value in {
                    "DB_USER": db_user,
                    "DB_PASSWORD": db_password,
                    "DB_HOST": db_host,
                    "DB_PORT": db_port,
                    "DB_NAME": db_name,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(
                    "DATABASE_URL is required when DEBUG is false, or set "
                    f"these database variables: {', '.join(missing)}"
                )
            self.DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

        if not self.gemini_api_keys:
            raise ValueError("Set GEMINI_API_KEYS, GOOGLE_API_KEY, or GEMINI_API_KEY for story generation.")

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v):
        if isinstance(v, str) and v.lower() in {"release", "prod", "production"}:
            return False
        return v

    @property
    def allowed_origins(self) -> List[str]:
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def gemini_api_key(self) -> Optional[str]:
        return self.GOOGLE_API_KEY or self.GEMINI_API_KEY

    @property
    def gemini_api_keys(self) -> List[str]:
        configured_keys = [
            key.strip()
            for key in (self.GEMINI_API_KEYS or "").split(",")
            if key.strip()
        ]
        fallback_keys = [
            key
            for key in [self.GOOGLE_API_KEY, self.GEMINI_API_KEY]
            if key
        ]
        return configured_keys or fallback_keys

    @property
    def job_execution_mode(self) -> str:
        if self.JOB_EXECUTION_MODE == "background" and os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            return "workflow" if self.STORY_WORKFLOW_ARN else "background"
        return self.JOB_EXECUTION_MODE

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
