from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    app_name:    str = "LiveDocAI"
    app_version: str = "1.0.0"
    debug:       bool = False
    secret_key:  str = "change-me-in-production"

    # Database
    database_url: str

    # Gemini (fallback)
    gemini_api_key: str = ""
    gemini_model:   str = "gemini-2.5-flash"

    # Groq (primary)
    grok_api_key: str = ""
    groq_model:   str = "llama-3.3-70b-versatile"

    # GitHub
    github_token: str = ""

    # CORS — comma separated list of allowed origins
    # Local:      http://localhost:5500,http://127.0.0.1:5500
    # Production: https://livedocai.vercel.app
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500,http://localhost:3000"

    def get_cors_origins(self) -> List[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        # Always allow localhost for development
        dev = ["http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:3000", "http://localhost:8000"]
        return list(set(origins + dev))

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
