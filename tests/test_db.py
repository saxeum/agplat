"""The migration runner, exercised without a database."""

import asyncio
from pathlib import Path

from agplat import db


class FakeTransaction:
    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class FakeConnection:
    def __init__(self, applied: set[str] | None = None) -> None:
        self.applied = applied or set()
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False

    async def execute(self, sql: str, *args: object) -> str:
        self.executed.append((sql, args))
        if sql.startswith("insert into schema_migrations"):
            self.applied.add(str(args[0]))
        return "OK"

    async def fetch(self, sql: str) -> list[dict[str, str]]:
        return [{"name": name} for name in self.applied]

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def close(self) -> None:
        self.closed = True


def write_migrations(directory: Path, names: list[str]) -> None:
    for name in names:
        (directory / name).write_text(f"-- {name}\n", encoding="utf-8")


def test_apply_skips_recorded_and_records_new(tmp_path: Path) -> None:
    write_migrations(tmp_path, ["0001_runs.sql", "0002_next.sql"])
    connection = FakeConnection(applied={"0001_runs.sql"})

    applied = asyncio.run(db._apply(connection, tmp_path))

    assert applied == ["0002_next.sql"]
    inserts = [args for sql, args in connection.executed if sql.startswith("insert")]
    assert inserts == [("0002_next.sql",)]


def test_migrate_connects_and_closes(monkeypatch, tmp_path: Path) -> None:
    write_migrations(tmp_path, ["0001_runs.sql"])
    connection = FakeConnection()
    seen: dict[str, str] = {}

    async def fake_connect(dsn: str) -> FakeConnection:
        seen["dsn"] = dsn
        return connection

    monkeypatch.setattr(db.asyncpg, "connect", fake_connect)

    applied = asyncio.run(db.migrate("postgresql://example", tmp_path))

    assert applied == ["0001_runs.sql"]
    assert seen["dsn"] == "postgresql://example"
    assert connection.closed
