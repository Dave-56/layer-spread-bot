"""The engine's safety rules: paper by default, keys never echoed, local requests only."""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

SECRET = "lyr_do_not_echo_0123456789"


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path):  # noqa: ANN001, ANN201
    monkeypatch.setenv("LAYER_API_KEY", SECRET)
    monkeypatch.setenv("BOT_STORE_DIR", str(tmp_path))
    for k in ("BOT_MODE", "KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY", "KALSHI_PRIVATE_KEY_PATH", "POLYMARKET_US_KEY_ID", "POLYMARKET_US_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    from spread_engine import app as module

    return importlib.reload(module)


def test_paper_by_default_and_keys_are_yes_no_only(engine) -> None:  # noqa: ANN001
    body = TestClient(engine.app).get("/status").json()
    assert body["mode"] == "paper"
    assert body["keys"] == {"layer": True, "kalshi": False, "polymarket_us": False}
    assert SECRET not in json.dumps(body)


def test_live_needs_the_exact_word(monkeypatch: pytest.MonkeyPatch) -> None:
    from spread_engine import config

    for value, mode in (("paper", "paper"), ("LIVE", "live"), ("yes", "paper"), ("", "paper")):
        monkeypatch.setenv("BOT_MODE", value)
        assert config.load().mode == mode


def test_answers_only_this_machine(engine) -> None:  # noqa: ANN001
    remote = TestClient(engine.app, client=("203.0.113.9", 5000))
    assert remote.get("/status").status_code == 403


def test_unknown_match_is_a_clear_404(engine) -> None:  # noqa: ANN001
    r = TestClient(engine.app).post("/best/preview", json={"match_id": "KXNOPE", "side": "yes", "size": 10})
    assert r.status_code == 404 and "Load matches first" in r.json()["detail"]
