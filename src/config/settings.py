"""Central configuration. Secrets come from the environment / .env, never from code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

GENERATED_DIR = PROJECT_ROOT / "data" / "generated"
SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"

DEFAULT_SEED = 42


@dataclass(frozen=True, repr=False)
class SnowflakeSettings:
    account: str | None
    user: str | None
    role: str | None
    warehouse: str | None
    database: str
    schema: str
    authenticator: str | None
    password: str | None = None
    private_key_path: str | None = None
    private_key_passphrase: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.account and self.user)

    def __repr__(self) -> str:  # never include secrets
        return f"SnowflakeSettings(account={self.account!r}, user={self.user!r}, database={self.database!r})"


def load_snowflake_settings() -> SnowflakeSettings:
    env = os.environ.get
    return SnowflakeSettings(
        account=env("SNOWFLAKE_ACCOUNT") or None,
        user=env("SNOWFLAKE_USER") or None,
        role=env("SNOWFLAKE_ROLE") or None,
        warehouse=env("SNOWFLAKE_WAREHOUSE") or None,
        database=env("SNOWFLAKE_DATABASE") or "CLOUDSPEND_AI",
        schema=env("SNOWFLAKE_SCHEMA") or "RAW",
        authenticator=env("SNOWFLAKE_AUTHENTICATOR") or None,
        password=env("SNOWFLAKE_PASSWORD") or None,
        private_key_path=env("SNOWFLAKE_PRIVATE_KEY_PATH") or None,
        private_key_passphrase=env("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE") or None,
    )


def load_app_snowflake_settings() -> tuple[SnowflakeSettings, bool]:
    """Settings for the dashboard. Uses the read-only SNOWFLAKE_APP_* login when configured, otherwise
    falls back to the pipeline login. Returns (settings, is_read_only)."""
    env = os.environ.get
    base = load_snowflake_settings()
    user = env("SNOWFLAKE_APP_USER")
    if not user:
        return base, False
    from dataclasses import replace

    return replace(
        base,
        user=user,
        role=env("SNOWFLAKE_APP_ROLE") or "CLOUDSPEND_READER",
        password=env("SNOWFLAKE_APP_PASSWORD") or None,
        private_key_path=env("SNOWFLAKE_APP_PRIVATE_KEY_PATH") or None,
        private_key_passphrase=env("SNOWFLAKE_APP_PRIVATE_KEY_PASSPHRASE") or None,
        authenticator=env("SNOWFLAKE_APP_AUTHENTICATOR") or None,
    ), True
