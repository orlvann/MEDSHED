# backend/config.py
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

    # Email Service (SMTP)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "localhost")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "1025"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "noreply@medshed.local")
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "MedShed System")

    # Twilio SMS
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "")

    # Frontend URL (for password reset links)
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
