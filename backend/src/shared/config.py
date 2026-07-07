"""Configuración central (pydantic-settings).

Incorpora BP-5 (auditoría): `log_level` es un conjunto cerrado; un valor
inválido rompe el arranque (fail-loud) en vez de degradar en silencio.
"""
from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AppEnv(StrEnum):
    development = "development"
    staging = "staging"
    production = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Autoken Facturas"
    app_version: str = "2.0.0"
    app_env: AppEnv = AppEnv.development
    log_level: LogLevel = LogLevel.INFO
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://autoken:autoken@localhost:5432/autoken"
    auto_migrate: bool = True

    jwt_secret: str = ""
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 14

    platform_admin_emails: str = ""

    storage_backend: str = "local"
    storage_local_dir: str = ".data/files"
    max_upload_mb: int = 15

    mistral_api_key: str = ""
    azure_docintel_endpoint: str = ""
    azure_docintel_key: str = ""

    vies_enabled: bool = True
    aeat_censal_enabled: bool = False
    aeat_cert_path: str = ""
    aeat_key_path: str = ""
    external_resolver_timeout_seconds: float = 6.0

    smtp_host: str = ""
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "soporte@autoken.es"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        return v.upper() if isinstance(v, str) else v

    @field_validator("database_url", mode="after")
    @classmethod
    def _asyncpg_driver(cls, v: str) -> str:
        # Replit/Neon entrega postgresql://…; el motor async requiere driver explícito.
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env is AppEnv.production


@lru_cache
def get_settings() -> Settings:
    return Settings()
