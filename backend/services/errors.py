# backend/services/errors.py
"""
Shared domain-level errors raised by services.

Why this exists:
- Services raise lightweight "machine-code" errors (ValueError-compatible)
  that routers can map to HTTP responses.
- Some errors can carry structured `.context` for FE (e.g., issues list),
  and optional `.detail` for a human-friendly message.
"""

from __future__ import annotations

from typing import Optional


class DomainError(ValueError):
    """
    Domain error that can carry extra context for the router.

    IMPORTANT:
    - __str__ returns only the machine code, so router logic that uses str(e)
      keeps working unchanged.
    - Router may optionally read `.context` and `.detail` to return structured
      error details to FE.
    """

    def __init__(self, code: str, *, context: Optional[dict] = None, detail: Optional[str] = None):
        super().__init__(code)
        self.code = code
        self.context = context
        self.detail = detail

    def __str__(self) -> str:
        return self.code
