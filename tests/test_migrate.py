"""The migration CLI wrapper."""

from types import SimpleNamespace

from agplat import migrate as migrate_module


def test_main_reports_applied(monkeypatch, capsys) -> None:
    async def fake_migrate(dsn: str) -> list[str]:
        assert dsn == "postgresql://example"
        return ["0001_baseline.sql"]

    monkeypatch.setattr(migrate_module, "migrate", fake_migrate)
    monkeypatch.setattr(
        migrate_module,
        "get_settings",
        lambda: SimpleNamespace(db_url="postgresql://example"),
    )

    migrate_module.main()

    assert "applied: 0001_baseline.sql" in capsys.readouterr().out


def test_main_reports_up_to_date(monkeypatch, capsys) -> None:
    async def fake_migrate(dsn: str) -> list[str]:
        return []

    monkeypatch.setattr(migrate_module, "migrate", fake_migrate)
    monkeypatch.setattr(
        migrate_module,
        "get_settings",
        lambda: SimpleNamespace(db_url="postgresql://example"),
    )

    migrate_module.main()

    assert "database is up to date" in capsys.readouterr().out
