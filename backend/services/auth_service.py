"""
Auth Service — login, tokens, roles.

Purpose:
- Handle user login and authentication.
- Generate and verify JWT tokens.
- Enforce role-based access (admin vs doctor).

Responsibilities:
- Validate credentials, hash/verify passwords.
- Issue short-lived access tokens (and optional refresh tokens).
- Decode/verify tokens and expose identity + roles to routers/services.
- Centralize auth-related errors and security policies.

Depends on:
- ORM: User
- config.py (JWT secret, token TTL)
- Password hashing (e.g., passlib)

Notes:
- This service is called by routers; it should not import FastAPI objects.
- Keep token payload minimal and privacy-safe.
"""
