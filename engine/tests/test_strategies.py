"""The strategies folder: every file is a choice, the examples pick what they say, the template makes no trade."""

from __future__ import annotations

from datetime import UTC, datetime

from uselayer import Match

from spread_engine import strategies
from spread_engine.views import over

LATER = "2099-01-01T00:00:00Z"


def m(mid: str, when: str | None = LATER, caveats: list[str] | None = None, close: str | None = None) -> Match:
    return Match.model_validate(
        {
            "caveats": caveats or [],
            "kalshi": {"market_id": mid, "outcome": mid, "event_time": when, "close_time": close},
            "polymarket_us": {"market_id": f"pm-{mid}"},
        }
    )


class _Leg:
    def __init__(self, venue: str, yes_ask: float | None) -> None:
        self.venue, self.yes_ask = venue, yes_ask


class _Prices:
    def __init__(self, k: float | None, u: float | None) -> None:
        self.a, self.b = _Leg("kalshi", k), _Leg("polymarket_us", u)

    def leg(self, venue: str) -> _Leg:
        return self.a if venue == "kalshi" else self.b


class _Info:
    def __init__(self, open_: bool) -> None:
        self.open = open_


class _Client:
    """Fake prices: {kalshi ticker: (Kalshi YES ask, Polymarket US YES ask)}, and the markets that aren't open."""

    def __init__(self, asks: dict[str, tuple[float | None, float | None]], closed: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.asks, self.closed = asks, closed

    def market(self, market_id: str, *, venue: str) -> _Info:
        return _Info(market_id not in self.closed)

    def prices(self, match: Match) -> _Prices:
        return _Prices(*self.asks[match.kalshi.market_id])


def test_every_file_is_a_choice_with_the_template_last() -> None:
    ids = [s["id"] for s in strategies.available()]
    assert ids[:4] == ["first_match", "favorite", "underdog", "venues_disagree"]
    assert ids[-1] == "my_strategy"


def test_first_match_skips_started_rules_and_empty_books() -> None:
    ms = [m("PAST", "2020-01-01T00:00:00Z"), m("RULES", caveats=["timing_differs"]), m("EMPTY"), m("OK")]
    sig = strategies.get("first_match")(ms, _Client({"EMPTY": (None, 0.4), "OK": (0.41, 0.42)}))  # type: ignore[arg-type]
    assert sig is not None and sig.match.kalshi.market_id == "OK" and (sig.side, sig.size) == ("yes", 100)
    assert sig.why


def test_examples_pick_what_they_say() -> None:
    ms = [m("A"), m("B"), m("C")]
    c = _Client({"A": (0.62, 0.64), "B": (0.25, 0.27), "C": (0.45, 0.52)})
    fav = strategies.get("favorite")(ms, c)  # type: ignore[arg-type]
    dog = strategies.get("underdog")(ms, c)  # type: ignore[arg-type]
    gap = strategies.get("venues_disagree")(ms, c)  # type: ignore[arg-type]
    assert fav and fav.match.kalshi.market_id == "A"
    assert dog and dog.match.kalshi.market_id == "B" and dog.max_price == 0.30
    assert gap and gap.match.kalshi.market_id == "C" and "7¢" in gap.why


def test_examples_skip_closed_markets_and_dead_books() -> None:
    # Each example would pick the first market here if it didn't check: Kalshi's market is closed
    # (1¢ vs 50¢: the widest gap, the cheapest YES), then 99¢ and 1¢ books with no real price.
    ms = [m("SHUT"), m("PMSHUT"), m("NINETYNINE"), m("ONE"), m("A"), m("B")]
    c = _Client(
        {"SHUT": (0.01, 0.50), "PMSHUT": (0.97, 0.02), "NINETYNINE": (0.99, 0.98), "ONE": (0.01, 0.02), "A": (0.62, 0.64), "B": (0.25, 0.29)},
        closed={"SHUT", "pm-PMSHUT"},
    )
    picked = {sid: strategies.get(sid)(ms, c) for sid in ("first_match", "favorite", "underdog", "venues_disagree")}  # type: ignore[arg-type]
    assert {sid: s.match.kalshi.market_id for sid, s in picked.items() if s} == {
        "first_match": "A",
        "favorite": "A",
        "underdog": "B",
        "venues_disagree": "B",
    }


def test_priced_can_include_rule_differences() -> None:
    ms = [m("RULES", caveats=["source_differs"]), m("OK")]
    c = _Client({"RULES": (0.4, 0.42), "OK": (0.5, 0.52)})
    assert [x.kalshi.market_id for x, _ in strategies.priced(ms, c)] == ["OK"]  # type: ignore[arg-type]
    assert [x.kalshi.market_id for x, _ in strategies.priced(ms, c, rules_differ_ok=True)] == ["RULES", "OK"]  # type: ignore[arg-type]


def test_template_makes_no_trade() -> None:
    assert strategies.get("my_strategy")([m("A")], _Client({"A": (0.5, 0.5)})) is None  # type: ignore[arg-type]


def test_readme_example_runs() -> None:
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text()
    code = readme.split("## Add your strategy", 1)[1].split("```python", 1)[1].split("```", 1)[0]
    ns: dict = {}
    exec(code.replace("from . import", "from spread_engine.strategies import"), ns)  # noqa: S102
    sig = ns["decide"]([m("A"), m("B")], _Client({"A": (0.45, 0.39), "B": (0.35, 0.38)}))
    assert sig is not None and sig.match.kalshi.market_id == "B" and sig.max_price == 0.40


def test_over() -> None:
    now = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
    assert over(m("X", "2026-10-03T21:00:00Z"), now)  # started 31 h ago
    assert not over(m("X", "2026-10-05T01:00:00Z"), now)  # in play
    assert over(m("X", "2026-10-05T20:00:00Z", close="2026-10-05T03:00:00Z"), now)  # closed
    assert not over(m("X", None), now)
