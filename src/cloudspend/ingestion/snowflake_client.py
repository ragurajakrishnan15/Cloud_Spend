"""Snowflake connection handling. Supports password, key-pair, and SSO (externalbrowser)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import snowflake.connector

from config.settings import PROJECT_ROOT, SnowflakeSettings, load_snowflake_settings

SQL_DIR = PROJECT_ROOT / "sql"


class SnowflakeConfigError(RuntimeError):
    pass


def _load_private_key_der(path: str, passphrase: str | None) -> bytes:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(
        Path(path).read_bytes(), password=passphrase.encode() if passphrase else None
    )
    return key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def connection_params(s: SnowflakeSettings) -> dict:
    if not s.is_configured:
        raise SnowflakeConfigError("SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER must be set (see .env.example).")
    params: dict = {"account": s.account, "user": s.user, "database": s.database, "schema": s.schema}
    if s.role:
        params["role"] = s.role
    if s.warehouse:
        params["warehouse"] = s.warehouse
    if s.private_key_path:
        params["private_key"] = _load_private_key_der(s.private_key_path, s.private_key_passphrase)
    elif s.authenticator:
        params["authenticator"] = s.authenticator
    elif s.password:
        params["password"] = s.password
    else:
        raise SnowflakeConfigError("No auth method: set a password, a private key path, or an authenticator.")
    return params


@contextmanager
def get_connection(settings: SnowflakeSettings | None = None, **overrides) -> Iterator[snowflake.connector.SnowflakeConnection]:
    """Yield a connection and always close it. Overrides (e.g. database=None) replace params."""
    params = connection_params(settings or load_snowflake_settings())
    params.update(overrides)
    params = {k: v for k, v in params.items() if v is not None}
    conn = snowflake.connector.connect(**params)
    try:
        yield conn
    finally:
        conn.close()


def run_sql_file(conn, path: Path) -> None:
    for _ in conn.execute_string(path.read_text(encoding="utf-8")):
        pass


def setup_warehouse(conn) -> list[str]:
    """Run the Phase 2 setup scripts in order."""
    ran = []
    for name in ("01_create_database.sql", "02_create_raw_tables.sql"):
        run_sql_file(conn, SQL_DIR / name)
        ran.append(name)
    return ran
