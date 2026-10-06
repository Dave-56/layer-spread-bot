"""The strategies folder: templates named the way traders talk, grouped by category; each picks what it
says from MADE-UP markets (no network), skips closed markets and dead books, and says why when it
makes no trade. Adding your own file checks that it loads."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from uselayer import Match

from spread_engine import strategies
from spread_engine.strategies import NoTrade, Signal
from spread_engine.views import over

NOW = datetime.now(UTC)


def iso(hours: float) -> str:
    return (NOW + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def m(
    mid: str,
    starts: float | None = 48,
    *,
    series: str = "KXMADEUPGAME",
    caveats: list[str] | None = None,
    close: float | None = None,
    pm_close: float | None = None,
    when: str | None = None,
) -> Match:
    return Match.model_validate(
        {
            "caveats": caveats or [],
            "kalshi": {
                "market_id": mid,
                "series": series,
                "event": f"Made-up event {mid}",
                "outcome": mid,
                "event_time": when if when is not None else (iso(starts) if starts is not None else None),
                "close_time": iso(close) if close is not None else None,
            },
            "polymarket_us": {"market_id": f"pm-{mid}", "close_time": iso(pm_close) if pm_close is not None else None},
        }
    )


class _Leg:
    def __init__(self, venue: str, yes_ask: float | None, no_ask: float | None) -> None:
        self.venue, self.yes_ask, self.no_ask = venue, yes_ask, no_ask


class _Prices:
    def __init__(self, k: float | None, u: float | None, k_no: float | None = None, u_no: float | None = None) -> None:
        self.a, self.b = _Leg("kalshi", k, k_no), _Leg("polymarket_us", u, u_no)

    def leg(self, venue: str) -> _Leg:
        return self.a if venue == "kalshi" else self.b


class _Info:
    def __init__(self, open_: bool) -> None:
        self.open = open_


class _Client:
    """Fake prices: {kalshi ticker: (Kalshi YES ask, Polymarket US YES ask[, Kalshi NO ask, Polymarket US NO ask])},
    and the market ids that aren't open."""

    def __init__(self, asks: dict[str, tuple], closed: frozenset[str] = frozenset()) -> None:
        self.asks, self.closed = asks, closed
        self.read: list[str] = []

    def market(self, market_id: str, *, venue: str) -> _Info:
        return _Info(market_id not in self.closed)

    def prices(self, match: Match) -> _Prices:
        self.read.append(match.kalshi.market_id)
        return _Prices(*self.asks[match.kalshi.market_id])


def run(sid: str, ms: list[Match], c: _Client) -> Signal | NoTrade | None:
    return strategies.get(sid)(ms, c)  # type: ignore[arg-type]


# ---- the list -------------------------------------------------------------------------------------


def test_templates_are_grouped_by_category_with_yours_last() -> None:
    rows = strategies.available()
    assert [(r["category"], r["id"]) for r in rows] == [
        ("Sports", "sports_favorite"),
        ("Sports", "sports_longshot"),
        ("Sports", "sports_game_day"),
        ("Crypto", "crypto_near_certain"),
        ("News, politics & economics", "news_near_certain"),
    ]  # my_strategy.py, the starter file, isn't listed: it never trades. The app offers it as a download.
    for r in rows:
        assert r["name"] and r["description"] and r["error"] is None
        text = (r["name"] + r["description"]).lower()
        assert "risk-free" not in text and "best execution" not in text and "guarantee" not in text


# ---- each template picks what it says --------------------------------------------------------------


def test_back_the_favorite_takes_the_next_game_and_skips_spreads() -> None:
    ms = [
        m("LATER", 30),
        m("SPREAD", 1, series="KXMADEUPSPREAD"),  # a spread, not who wins
        m("SOON-DOG", 2),
        m("SOON-FAV", 2),
    ]
    c = _Client({"LATER": (0.70, 0.71), "SPREAD": (0.60, 0.61), "SOON-DOG": (0.35, 0.36), "SOON-FAV": (0.66, 0.65)})
    sig = run("sports_favorite", ms, c)
    assert isinstance(sig, Signal) and sig.match.kalshi.market_id == "SOON-FAV"
    assert (sig.side, sig.amount, sig.size, sig.max_price) == ("yes", 50, None, 0.85)
    assert "65¢ (65%)" in sig.why and "SPREAD" not in c.read


def test_longshot_under_20() -> None:
    ms = [m("A", 3), m("B", 3)]
    sig = run("sports_longshot", ms, _Client({"A": (0.70, 0.71), "B": (0.19, 0.18)}))
    assert isinstance(sig, Signal) and sig.match.kalshi.market_id == "B" and sig.max_price == 0.20
    none = run("sports_longshot", ms, _Client({"A": (0.70, 0.71), "B": (0.30, 0.31)}))
    assert none == NoTrade("None of the next games has a side priced under 20¢ right now.")


def test_game_day_only_looks_at_the_next_6_hours() -> None:
    ms = [m("TOMORROW", 20), m("TONIGHT", 3)]
    c = _Client({"TOMORROW": (0.70, 0.70), "TONIGHT": (0.60, 0.61)})
    sig = run("sports_game_day", ms, c)
    assert isinstance(sig, Signal) and sig.match.kalshi.market_id == "TONIGHT" and "starts in 3 hours" in sig.why
    assert run("sports_game_day", [m("TOMORROW", 20)], c) == NoTrade("No game matched on both venues starts in the next 6 hours.")


def test_crypto_says_why_when_layer_has_none() -> None:
    assert run("crypto_near_certain", [], _Client({})) == NoTrade(
        "Layer has no crypto markets matched on both Kalshi and Polymarket US right now."
    )


def test_crypto_buys_the_nearly_decided_side_close_to_its_deadline() -> None:
    ms = [m("BTC-FAR", None, series="KXBTCD", close=24 * 10), m("BTC-SOON", None, series="KXBTCD", close=30)]
    c = _Client({"BTC-FAR": (0.05, 0.06, 0.95, 0.94), "BTC-SOON": (0.06, 0.07, 0.95, 0.93)})
    sig = run("crypto_near_certain", ms, c)
    assert isinstance(sig, Signal) and sig.match.kalshi.market_id == "BTC-SOON" and sig.side == "no"
    assert sig.max_price == 0.97 and "93¢ (93%)" in sig.why and "BTC-FAR" not in c.read


def test_news_uses_the_earlier_close() -> None:
    # Kalshi closes at the result (1 day); Polymarket US two weeks later. The result is due in a day.
    ms = [m("CHART", None, series="KXMADEUPCHART", close=24, pm_close=24 * 15)]
    sig = run("news_near_certain", ms, _Client({"CHART": (0.95, 0.96)}))
    assert isinstance(sig, Signal) and sig.side == "yes" and "1.0 days before it closes" in sig.why
    far = [m("VOTE", None, close=24 * 300)]
    assert run("news_near_certain", far, _Client({"VOTE": (0.95, 0.96)})) == NoTrade(
        "None of the 1 news, politics, economics or culture markets matched on both venues closes in the next 7 days."
    )


def test_template_makes_no_trade_and_says_so() -> None:
    out = run("my_strategy", [m("A")], _Client({"A": (0.5, 0.5)}))
    assert isinstance(out, NoTrade) and "my_strategy.py" in out.why


# ---- every template skips what can't be compared --------------------------------------------------


@pytest.mark.parametrize("sid", ["sports_favorite", "sports_longshot", "sports_game_day"])
def test_sports_templates_skip_closed_markets_dead_books_and_rule_differences(sid: str) -> None:
    # Each would pick the first ones if it didn't check: Kalshi's market closed, Polymarket US's
    # closed, 1¢/99¢ books with no real price, worded differently.
    ms = [m("SHUT", 1), m("PMSHUT", 1), m("NINETYNINE", 1), m("ONE", 1), m("RULES", 1, caveats=["source_differs"]), m("FAV", 2), m("DOG", 2)]
    c = _Client(
        {"SHUT": (0.15, 0.60), "PMSHUT": (0.70, 0.10), "NINETYNINE": (0.99, 0.70), "ONE": (0.01, 0.12), "RULES": (0.70, 0.15), "FAV": (0.62, 0.64), "DOG": (0.17, 0.19)},
        closed=frozenset({"SHUT", "pm-PMSHUT"}),
    )
    sig = run(sid, ms, c)
    assert isinstance(sig, Signal) and sig.match.kalshi.market_id == {"sports_longshot": "DOG"}.get(sid, "FAV")
    assert set(c.read) <= {"NINETYNINE", "ONE", "FAV", "DOG"}  # closed and rule-different books are never read


def test_priced_keeps_the_order_and_can_include_rule_differences() -> None:
    ms = [m("RULES", caveats=["source_differs"]), m("OK1"), m("OK2"), m("OK3")]
    c = _Client({"RULES": (0.4, 0.42), "OK1": (0.5, 0.52), "OK2": (0.3, 0.31), "OK3": (0.6, 0.61)})
    assert [x.kalshi.market_id for x, _ in strategies.priced(ms, c)] == ["OK1", "OK2", "OK3"]  # type: ignore[arg-type]
    assert [x.kalshi.market_id for x, _ in strategies.priced(ms, c, rules_differ_ok=True, limit=2)] == ["RULES", "OK1"]  # type: ignore[arg-type]


# ---- adding your own ----------------------------------------------------------------------------------


@pytest.fixture()
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """A strategies folder of its own: files added here never touch the real one."""
    monkeypatch.setattr(strategies, "FOLDER", tmp_path)
    monkeypatch.setattr(strategies, "__path__", [str(tmp_path), *strategies.__path__])
    yield tmp_path
    for k in [k for k in sys.modules if k.startswith("spread_engine.strategies.mine_")]:
        del sys.modules[k]


GOOD = '''from . import SPORTS, NoTrade

NAME = "Mine"
CATEGORY = SPORTS
DESCRIPTION = "Never trades."


def decide(matches, client):
    return NoTrade("Mine never trades.")
'''


def test_add_a_file_and_it_is_listed(folder: Path) -> None:
    row = strategies.add("mine_one.py", GOOD)
    assert row == {**row, "id": "mine_one", "name": "Mine", "category": "Sports", "error": None}
    assert (folder / "mine_one.py").read_text() == GOOD
    assert [r["id"] for r in strategies.available()] == ["mine_one"]
    assert strategies.get("mine_one")([], None) == NoTrade("Mine never trades.")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "code", "says"),
    [
        ("mine_bad.py", "def decide(:\n", "mine_bad.py didn't load. Line 1:"),
        ("mine_nod.py", "NAME = 'x'\n", "mine_nod.py has no decide(matches, client) function."),
        ("mine_err.py", "raise RuntimeError('boom')\ndef decide(m, c): pass\n", "mine_err.py didn't load. Line 1: RuntimeError: boom"),
        ("Mine Strategy.txt", GOOD, "Name the file in lowercase letters"),
    ],
)
def test_a_file_that_does_not_load_is_refused_and_removed(folder: Path, name: str, code: str, says: str) -> None:
    with pytest.raises(strategies.BadStrategy) as e:
        strategies.add(name, code)
    assert str(e.value).startswith(says)
    assert list(folder.glob("*.py")) == []


def test_replacing_needs_a_yes_and_a_bad_replacement_keeps_the_old_file(folder: Path) -> None:
    strategies.add("mine_two.py", GOOD)
    with pytest.raises(strategies.BadStrategy, match="already a mine_two.py"):
        strategies.add("mine_two.py", GOOD.replace("Mine", "Mine 2"))
    with pytest.raises(strategies.BadStrategy):
        strategies.add("mine_two.py", "def decide(:\n", replace=True)
    assert (folder / "mine_two.py").read_text() == GOOD
    assert strategies.add("mine_two.py", GOOD.replace('"Mine"', '"Mine 2"'), replace=True)["name"] == "Mine 2"


def test_the_starter_file_cannot_be_replaced() -> None:
    with pytest.raises(strategies.BadStrategy, match="my_strategy.py is the starter file"):
        strategies.add("my_strategy.py", GOOD, replace=True)
    assert "def decide(" in strategies.starter()


def test_examples_cannot_be_replaced() -> None:
    with pytest.raises(strategies.BadStrategy, match="one of the examples"):
        strategies.add("sports_favorite.py", GOOD, replace=True)


def test_a_broken_file_in_the_folder_is_listed_with_why(folder: Path) -> None:
    (folder / "mine_broken.py").write_text("import nothing_called_this\n")
    (folder / "mine_ok.py").write_text(GOOD)
    rows = {r["id"]: r for r in strategies.available()}
    assert rows["mine_ok"]["error"] is None
    assert rows["mine_broken"]["error"] == "Line 1: ModuleNotFoundError: No module named 'nothing_called_this'"
    with pytest.raises(ValueError, match="didn't load"):
        strategies.get("mine_broken")


# ---- the README ---------------------------------------------------------------------------------------


def test_readme_example_runs() -> None:
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text()
    code = readme.split("### Add your own", 1)[1].split("```python", 1)[1].split("```", 1)[0]
    ns: dict = {}
    exec(code.replace("from . import", "from spread_engine.strategies import"), ns)  # noqa: S102
    c = _Client({"A": (0.45, 0.39), "B": (0.35, 0.38)})
    sig = ns["decide"]([m("A"), m("B")], c)
    assert isinstance(sig, Signal) and sig.match.kalshi.market_id == "B" and sig.max_price == 0.40
    assert isinstance(ns["decide"]([m("A")], c), NoTrade)


def test_over() -> None:
    now = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
    assert over(m("X", when="2026-10-03T21:00:00Z"), now)  # started 31 h ago
    assert not over(m("X", when="2026-10-05T01:00:00Z"), now)  # in play
    late = Match.model_validate(
        {"kalshi": {"market_id": "X", "event_time": "2026-10-05T20:00:00Z", "close_time": "2026-10-05T03:00:00Z"}, "polymarket_us": {"market_id": "pm-X"}}
    )
    assert over(late, now)  # closed
    assert not over(m("X", None), now)
