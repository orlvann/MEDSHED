"""
Application configuration.

Loads settings from environment variables with sensible defaults for development.
"""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""
    
    # JWT Configuration
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-in-production-min-32-chars")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///backend/db/sqlite.db")
    
    # CORS
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "")
    
    # Organization timezone (for period classification)
    ORG_TIMEZONE: str = os.getenv("ORG_TIMEZONE", "Europe/Warsaw")
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

