import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from app.config import settings

logger = logging.getLogger("dsentry.db")


def _resolve_schema_path() -> Path:
    here = Path(__file__).resolve()
    candidates: list[Path] = [
        Path.cwd() / "schemas" / "dsentry_sqlite.sql",
        Path("/hub/schemas/dsentry_sqlite.sql"),
    ]
    # Walk up from this file: repo layout needs parents[3]
    # (hub/api/app/database.py -> repo root), docker layout needs
    # parents[1] (/hub/app/database.py -> /hub). Iterating avoids
    # IndexError on shallow paths like /hub/app/database.py.
    for p in here.parents:
        candidates.append(p / "schemas" / "dsentry_sqlite.sql")
    for p in candidates:
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return candidates[0]


_SQLITE_SCHEMA_SQL: str | None = None


def _load_schema_sql() -> str:
    global _SQLITE_SCHEMA_SQL
    if _SQLITE_SCHEMA_SQL is not None:
        return _SQLITE_SCHEMA_SQL
    schema_path = _resolve_schema_path()
    try:
        with schema_path.open() as f:
            _SQLITE_SCHEMA_SQL = f.read()
    except FileNotFoundError as exc:
        # Starting without tables only fails later on the first request;
        # fail fast with a clear message instead.
        raise RuntimeError(f"SQLite schema file not found at {schema_path}") from exc
    return _SQLITE_SCHEMA_SQL


# Baseline schema version: the CREATE TABLE IF NOT EXISTS script above.
# Append (version, SQL) entries for every change that must be applied to an
# existing database (CREATE TABLE IF NOT EXISTS does not alter columns).
_SCHEMA_VERSION = 1
_MIGRATIONS: list[tuple[int, str]] = []


async def _apply_migrations(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    cursor = await db.execute("SELECT MAX(version) FROM schema_migrations")
    row = await cursor.fetchone()
    current = row[0] if row and row[0] is not None else 0
    if current == 0:
        # The baseline script has just been applied.
        await db.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            (_SCHEMA_VERSION,),
        )
        current = _SCHEMA_VERSION
    for version, script in _MIGRATIONS:
        if version <= current:
            continue
        await db.executescript(script)
        await db.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
        )
    await db.commit()


async def _init_schema(db: aiosqlite.Connection) -> None:
    sql = _load_schema_sql()
    await db.executescript(sql)
    await _apply_migrations(db)


async def init_sqlite() -> None:
    """Apply the schema once at startup.

    WAL is a persistent property of the database file, so it only needs to be
    set here, not on every connection.
    """
    sqlite_path = Path(settings.sqlite_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep SQLite sidecars (WAL/SHM) private as well. Explicit chmod below
    # covers the main file; the umask covers files SQLite creates later.
    try:
        os.umask(0o077)
    except OSError:
        pass
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await _init_schema(db)
    # The database holds push keys, alert targets/tokens, and password hashes.
    # Keep it private even on a shared host.
    try:
        sqlite_path.chmod(0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{sqlite_path}{suffix}")
            if sidecar.exists():
                sidecar.chmod(0o600)
    except OSError as exc:
        logger.warning("Could not restrict SQLite file permissions: %s", exc)
    logger.info("SQLite ready (WAL mode), schema applied")


@asynccontextmanager
async def open_db() -> AsyncIterator[aiosqlite.Connection]:
    """Open a fresh SQLite connection with the standard pragmas.

    One connection per request (or background task) keeps concurrent
    transactions from interleaving statements and each other's commits.
    The connect timeout makes competing `BEGIN IMMEDIATE` writers queue on
    SQLite's busy handler instead of failing immediately with SQLITE_BUSY.
    """
    db = await aiosqlite.connect(settings.sqlite_path, timeout=30.0)
    db.row_factory = aiosqlite.Row
    try:
        await db.execute("PRAGMA foreign_keys=ON")
        yield db
    finally:
        await db.close()
