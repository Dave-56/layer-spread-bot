"""Replay of a recording, on a MADE-UP recording (no network): a gap opens for 5 seconds, then closes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spread_engine import replay as r
from spread_engine.funnel import ScanSettings

MATCH = {
    "confidence": 0.97,
    "caveats": [],
    "kalshi": {"venue": "kalshi", "market_id": "KXTEST-26OCT10-A", "event": "Made-up A vs B", "outcome": "A", "event_time": "2026-10-10T20:00:00Z", "close_time": "2026-10-11T04:00:00Z"},
    "polymarket_us": {"venue": "polymarket_us", "market_id": "aec-test-a-b", "slug": "aec-test-a-b", "outcome": "A", "event_time": "2026-10-10T20:00:00Z", "close_time": "2026-10-11T04:00:00Z"},
}


def book(venue: str, market: str, at: str, bid: float, ask: float) -> dict:
    return {"kind": "book", "venue": venue, "market": market, "bids": [{"price": bid, "size": 500.0}], "asks": [{"price": ask, "size": 500.0}], "as_of": at, "source": "venue"}


@pytest.fixture()
def recording(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(r, "RECORDINGS", tmp_path)
    lines = [
        # 0 s: YES on Kalshi 41¢ + NO on Polymarket US (1 − 58¢ bid = 42¢) = 83¢ for a $1 payout.
        book("kalshi", "KXTEST-26OCT10-A", "2026-10-10T12:00:00Z", 0.39, 0.41),
        book("polymarket_us", "aec-test-a-b", "2026-10-10T12:00:00Z", 0.58, 0.60),
        book("kalshi", "KXTEST-26OCT10-A", "2026-10-10T12:00:03Z", 0.39, 0.41),
        # 5 s: Polymarket US moves; the pair now costs $1.01 → no gap.
        book("polymarket_us", "aec-test-a-b", "2026-10-10T12:00:05Z", 0.40, 0.42),
        book("kalshi", "KXTEST-26OCT10-A", "2026-10-10T12:00:09Z", 0.40, 0.42),
    ]
    name = "KXTEST-26OCT10-A-20261010T1200Z.jsonl"
    (tmp_path / name).write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    r.sidecar(tmp_path / name).write_text(json.dumps(MATCH))
    return name


def test_replay_finds_the_gap_and_how_long_it_lasted(recording: str) -> None:
    out = r.replay(recording, ScanSettings(size=10))
    assert out["from"].startswith("2026-10-10T12:00:00")
    assert out["counts"]["survivor"] >= 1 and out["counts"]["no_gap"] >= 1
    best = out["best_survivor"]
    assert best["at"].startswith("2026-10-10T12:00:0")
    q = best["quote"]
    assert q["gross_at_best"] == pytest.approx(0.17)
    assert q["net_profit"] > 0 and q["net_profit"] == pytest.approx(q["gross_spread"] - q["fees"], abs=1e-6)
    assert q["return_per_day_pct"] is not None  # payout time from the match, as the SDK's profit() rule
    assert out["longest_survivor_s"] == pytest.approx(5.0)


def test_short_side_twin_is_priced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A Polymarket US twin on the short side: record_stream("<slug>:short") writes that side's book
    # under the same id the match uses.
    monkeypatch.setattr(r, "RECORDINGS", tmp_path)
    m = json.loads(json.dumps(MATCH))
    m["polymarket_us"]["market_id"] = "aec-test-a-b:short"
    lines = [
        book("kalshi", "KXTEST-26OCT10-A", "2026-10-10T12:00:00Z", 0.39, 0.41),
        book("polymarket_us", "aec-test-a-b:short", "2026-10-10T12:00:01Z", 0.40, 0.42),
        book("kalshi", "KXTEST-26OCT10-A", "2026-10-10T12:00:03Z", 0.39, 0.41),
    ]
    (tmp_path / "s.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    r.sidecar(tmp_path / "s.jsonl").write_text(json.dumps(m))
    out = r.replay("s.jsonl", ScanSettings(size=10))
    assert out["moments"] >= 1 and out["counts"]["unpriced"] == 0
    assert out["best"]["quote"]["gross_at_best"] is not None


def test_list_files_reads_the_sidecar(recording: str) -> None:
    files = r.list_files()
    assert files[0]["file"] == recording
    assert files[0]["match"]["id"] == "KXTEST-26OCT10-A"
    assert files[0]["markets"] == {"kalshi": ["KXTEST-26OCT10-A"], "polymarket_us": ["aec-test-a-b"]}
    assert files[0]["top_of_book_only"] is True  # one level a side in this made-up file


def test_a_file_without_a_saved_match_is_paired_by_lookup(recording: str, tmp_path: Path) -> None:
    from uselayer import Match

    other = tmp_path / "picked"
    other.mkdir()
    (other / "gaps.jsonl").write_text((tmp_path / recording).read_text())  # no .match.json beside it
    asked: list[str] = []

    def lookup(ticker: str) -> Match | None:
        asked.append(ticker)
        return Match.model_validate(MATCH)

    out = r.replay(str(other / "gaps.jsonl"), ScanSettings(size=10), lookup=lookup)
    assert asked == ["KXTEST-26OCT10-A"] and out["counts"]["survivor"] >= 1
    assert out["top_of_book_only"] is True
    assert {f["file"] for f in r.list_files(str(other))} == {recording, "gaps.jsonl"}


def test_placeholder_sizes_price_one_contract_and_say_size_unknown(recording: str, tmp_path: Path) -> None:
    (tmp_path / recording).with_suffix(".meta.json").write_text(
        json.dumps({"settles_at": "2026-10-11T03:00:00Z", "note": "sizes are placeholders: the source has no depth"})
    )
    out = r.replay(recording, ScanSettings(size=100))
    assert out["size_unknown"] is True and out["top_of_book_only"] is True
    q = out["best_survivor"]["quote"]
    assert q["contracts"] == 1  # per contract only; never the placeholder size as depth
    assert out["settles_at"] == "2026-10-11T03:00:00+00:00"  # the meta's payout time wins
    assert r.list_files()[0]["size_unknown"] is True


def test_no_pair_in_the_file_says_how_to_record(recording: str, tmp_path: Path) -> None:
    (tmp_path / "lonely.jsonl").write_text((tmp_path / recording).read_text().splitlines()[0] + "\n")
    with pytest.raises(LookupError, match="npm run record"):
        r.replay("lonely.jsonl", ScanSettings(), lookup=lambda t: None)


def test_only_files_inside_recordings(recording: str) -> None:
    with pytest.raises(FileNotFoundError):
        r.replay("../../etc/passwd", ScanSettings())


def test_payout_rule() -> None:
    from uselayer import Match

    at = r.payout_at(Match.model_validate(MATCH))
    assert at is not None and at.isoformat() == "2026-10-11T02:00:00+00:00"  # later event + 6 h, before the close
