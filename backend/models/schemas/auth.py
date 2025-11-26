# backend/models/schemas/auth.py

from typing import Literal

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """Login form payload."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """
    JWT response returned on successful login.

    Contract (MVP):
      { "access_token": "<jwt>", "token_type": "Bearer" }
    """

    access_token: str
    token_type: Literal["Bearer"] = "Bearer"

    model_config = {
        "json_schema_extra": {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIs...",
                "token_type": "Bearer",
            }
        }
    }
