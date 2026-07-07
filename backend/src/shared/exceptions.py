"""Excepciones de dominio comunes."""
from __future__ import annotations


class DomainError(Exception):
    """Error de negocio con mensaje apto para el usuario."""

    status_code = 400


class NotFoundError(DomainError):
    status_code = 404


class ForbiddenError(DomainError):
    status_code = 403


class ConflictError(DomainError):
    status_code = 409
