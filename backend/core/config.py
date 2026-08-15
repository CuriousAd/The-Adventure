from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator
import os

class Settings(BaseSettings):
    API_PREFIX: str = "/api"
    DEBUG: bool = False

    DATABASE_URL: Optional[str] = None

    ALLOWED_ORIGINS: str = ""

    OPENAI_API_KEY: str

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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
