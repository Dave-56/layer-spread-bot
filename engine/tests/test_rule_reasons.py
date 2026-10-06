"""Why the rules differ: Layer's sentence per caveat travels with the match, under the amber warning."""

from __future__ import annotations

from typing import Any

from uselayer import Match

from spread_engine.replay import layer_match
from spread_engine.views import match_view, pair_view, rule_reasons, rule_warning

SOURCE = "Kalshi settles on the league's official box score; Polymarket US uses ESPN."
TIMING = "Kalshi counts the game by its Eastern date; Polymarket US by UTC."


def match(caveats: list[str], notes: dict[str, str] | None = None) -> Match:
    d: dict[str, Any] = {
        "caveats": caveats,
        "confidence": 0.97,
        "kalshi": {"market_id": "KXTEST-1", "event": "Team A vs Team B", "outcome": "Team A"},
        "polymarket_us": {"market_id": "aec-test-a", "outcome": "Team A"},
    }
    if notes is not None:
        d["caveat_notes"] = notes
    return Match.model_validate(d)


def test_reasons_in_caveat_order_with_the_warning_unchanged() -> None:
    m = match(["timing_differs", "source_differs"], {"source_differs": SOURCE, "timing_differs": f" {TIMING} "})
    assert rule_reasons(m) == [TIMING, SOURCE]
    assert rule_warning(m) == (
        "Rules differ slightly on when the result is checked (deadline or timezone) and where the result comes from. "
        "Both pay the same in normal cases, but in a rare case one could pay and the other not."
    )
    assert match_view(m)["rule_reasons"] == [TIMING, SOURCE]
    assert pair_view(m)["rule_reasons"] == [TIMING, SOURCE]


def test_no_reasons_when_layer_sent_none_so_the_warning_stands_alone() -> None:
    for m in (match(["source_differs"]), match(["source_differs"], {}), match(["source_differs"], {"source_differs": "  "})):
        assert rule_reasons(m) == []
        assert match_view(m)["rule_warning"] is not None


def test_only_notes_for_the_match_s_own_caveats() -> None:
    assert rule_reasons(match([], {"source_differs": SOURCE})) == []
    assert rule_reasons(match(["timing_differs"], {"source_differs": SOURCE})) == []


class FakeClient:
    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer

    def match(self, *_: Any, **__: Any) -> dict[str, Any]:
        return self.answer


def test_a_replay_keeps_the_notes_from_layer() -> None:
    side = {"market_id": "KXTEST-1", "venue": "kalshi"}
    twin = {"market_id": "aec-test-a", "venue": "polymarket_us"}
    answer = {"source_market": side, "matched_market": twin, "caveats": ["source_differs"], "caveat_notes": {"source_differs": SOURCE}}
    assert rule_reasons(layer_match(FakeClient(answer), "KXTEST-1")) == [SOURCE]  # type: ignore[arg-type]
    del answer["caveat_notes"]
    assert rule_reasons(layer_match(FakeClient(answer), "KXTEST-1")) == []  # type: ignore[arg-type]
