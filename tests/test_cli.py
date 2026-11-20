"""The ``python -m agplat`` entry point is a thin uvicorn wrapper."""

from agplat import __main__ as cli


def test_main_starts_uvicorn(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> None:
        calls["args"] = args
        calls["kwargs"] = kwargs

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    cli.main()

    assert calls["args"] == ("agplat.main:create_app",)
    assert calls["kwargs"] == {
        "factory": True,
        "host": "127.0.0.1",
        "port": 8000,
        "reload": True,
    }
