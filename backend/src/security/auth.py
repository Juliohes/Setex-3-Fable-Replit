"""Autenticación: Argon2id + JWT corto + refresh rotativo con detección de reuso.

- Access token: 15 min, incluye tenant_id y rol; si el tenant del token no
  coincide con el resuelto por host/cabecera ⇒ 403 (plan §3.3).
- Refresh: opaco (aleatorio), guardado hasheado (SHA-256). Rotación en cada
  uso; si se presenta un refresh YA rotado (robo) ⇒ se revoca la familia entera.
- platform_admin: 2FA TOTP obligatorio.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from identity.models import RefreshToken
from shared.config import get_settings
from shared.exceptions import ForbiddenError
from shared.uuid7 import uuid7

_hasher = PasswordHasher()  # Argon2id por defecto


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def create_access_token(
    subject_type: str, subject_id: uuid.UUID, tenant_id: uuid.UUID | None, role: str
) -> str:
    settings = get_settings()
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET no configurado (fail-loud)")
    payload = {
        "sub": str(subject_id),
        "typ": subject_type,
        "tid": str(tenant_id) if tenant_id else None,
        "role": role,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + dt.timedelta(seconds=settings.jwt_access_ttl_seconds)).timestamp()),
        "jti": str(uuid7()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ForbiddenError("Credenciales inválidas o caducadas") from exc


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue_refresh_token(
    session: AsyncSession,
    subject_type: str,
    subject_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    family_id: uuid.UUID | None = None,
) -> str:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            subject_type=subject_type,
            subject_id=subject_id,
            tenant_id=tenant_id,
            family_id=family_id or uuid7(),
            token_hash=_hash_refresh(raw),
            expires_at=_now() + dt.timedelta(seconds=settings.jwt_refresh_ttl_seconds),
        )
    )
    return raw


async def rotate_refresh_token(session: AsyncSession, raw: str) -> tuple[RefreshToken, str]:
    """Devuelve (token_antiguo, nuevo_refresh_crudo). Reuso ⇒ revoca familia."""
    row = await session.execute(select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh(raw)))
    token = row.scalar_one_or_none()
    if token is None:
        raise ForbiddenError("Refresh token desconocido")
    if token.revoked_at is not None:
        # Reuso detectado: alguien presenta un token ya rotado ⇒ revocar TODA la familia.
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id)
            .values(revoked_at=_now())
        )
        raise ForbiddenError("Refresh token reutilizado: sesión revocada por seguridad")
    if token.expires_at < _now():
        raise ForbiddenError("Refresh token caducado")
    token.revoked_at = _now()
    new_raw = await issue_refresh_token(
        session, token.subject_type, token.subject_id, token.tenant_id, token.family_id
    )
    return token, new_raw
