# backend/models/schemas/auth.py

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


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


class SetPasswordRequest(BaseModel):
    """Request to set/reset password using a token."""

    token: str = Field(..., min_length=10, description="Password reset token from email")
    new_password: str = Field(..., min_length=8, description="New password (minimum 8 characters)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "token": "xF3k9Lm2nQ8pR7wV...",
                "new_password": "MySecurePassword123!",
            }
        }
    }


class SetPasswordResponse(BaseModel):
    """Response after successfully setting password."""

    message: str = "Password set successfully"

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Password set successfully",
            }
        }
    }
