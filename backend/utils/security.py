"""
Security utilities (to be implemented).

Provide:
- hash_password(plain: str) -> str
- verify_password(plain: str, hashed: str) -> bool
- generate_temp_password(length: int = 12) -> str

Policy:
- For ALL newly created users (admin via users router, doctor via auto-provision),
  the system SHOULD set `must_change_password=True` to enforce a first-login reset.
- Use a strong KDF (argon2/bcrypt) in production.
- Never return or log plaintext passwords.
"""
