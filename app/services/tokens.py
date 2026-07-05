from __future__ import annotations

import hashlib
import secrets


def generate_public_token() -> str:
    return secrets.token_urlsafe(24)[:32]


def hash_public_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
