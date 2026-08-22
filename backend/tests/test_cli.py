import logging

from jellyguard import cli


def test_cli_suppresses_credential_bearing_http_client_logs(monkeypatch):
    httpx_logger = logging.getLogger("httpx")
    httpcore_logger = logging.getLogger("httpcore")
    previous_levels = (httpx_logger.level, httpcore_logger.level)
    captured = {}
    app = object()

    monkeypatch.setattr(cli, "create_app", lambda: app)
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda passed_app, **kwargs: captured.update(app=passed_app, kwargs=kwargs),
    )

    try:
        httpx_logger.setLevel(logging.INFO)
        httpcore_logger.setLevel(logging.INFO)
        cli.main()

        assert httpx_logger.level == logging.WARNING
        assert httpcore_logger.level == logging.WARNING
        assert captured == {
            "app": app,
            "kwargs": {"host": "127.0.0.1", "port": 8000},
        }
    finally:
        httpx_logger.setLevel(previous_levels[0])
        httpcore_logger.setLevel(previous_levels[1])
