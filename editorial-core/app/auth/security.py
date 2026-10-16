"""
Primitives de sécurité : hachage des mots de passe (bcrypt) et jetons JWT (HS256).
"""
from __future__ import annotations

import datetime as dt
import hmac
from typing import Any

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"
ROLES = ("admin", "editor")
PASSWORD_MIN_LENGTH = 12

# Hash factice utilisé quand l'utilisateur n'existe pas : on vérifie quand même
# un mot de passe pour que le temps de réponse ne révèle pas l'existence du compte.
_DUMMY_HASH = bcrypt.hashpw(b"timing-attack-protection", bcrypt.gensalt()).decode()


class TokenError(Exception):
    """Jeton absent, expiré ou invalide."""


def validate_password_strength(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Le mot de passe doit contenir au moins {PASSWORD_MIN_LENGTH} caractères.")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Le mot de passe ne doit pas dépasser 72 octets (limite bcrypt).")


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    candidate = password.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(candidate, (password_hash or _DUMMY_HASH).encode()) and password_hash is not None
    except ValueError:
        return False


def create_access_token(*, user_id: int, username: str, role: str, token_version: int,
                        expires_minutes: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "usr": username,
        "role": role,
        "ver": token_version,
        "iat": now,
        "nbf": now,
        "exp": now + dt.timedelta(minutes=expires_minutes),
        "iss": settings.JWT_ISSUER,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=settings.JWT_ISSUER,
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc


def match_service_api_key(candidate: str) -> bool:
    """Compare une clé API de service à celles configurées (temps constant)."""
    found = False
    for key in settings.service_api_keys:
        if hmac.compare_digest(candidate.encode(), key.encode()):
            found = True
    return found
