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


def book(venue: str, market: str, at: str, bid: float, ask: float, size: float = 500.0) -> dict:
    return {"kind": "book", "venue": venue, "market": market, "bids": [{"price": bid, "size": size}], "asks": [{"price": ask, "size": size}], "as_of": at, "source": "venue"}


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


def test_placeholder_sizes_price_the_assumed_size_and_say_so(recording: str, tmp_path: Path) -> None:
    (tmp_path / recording).with_suffix(".meta.json").write_text(
        json.dumps({"settles_at": "2026-10-11T03:00:00Z", "note": "sizes are placeholders: the source has no depth"})
    )
    out = r.replay(recording, ScanSettings(size=100))
    assert out["size_unknown"] is True and out["top_of_book_only"] is True
    assert out["assumed_size"] == 100
    assert out["size_note"] == "Size unknown: assumes 100 contracts at the top price on both venues."
    q = out["best_survivor"]["quote"]
    assert q["contracts"] == 100 and q["a"]["contracts_at_best"] == 100  # the assumption, labelled
    assert out["settles_at"] == "2026-10-11T03:00:00+00:00"  # the meta's payout time wins
    assert r.list_files()[0]["size_unknown"] is True


def thin_gap(tmp_path: Path, day: str = "2026-10-10") -> str:
    """A MADE-UP file with placeholder sizes (1 a level): YES on Kalshi at 97¢ + NO on Polymarket US at 2¢ = a 1¢ gap."""
    lines = [
        book("kalshi", "KXTEST-26OCT10-A", f"{day}T12:00:00Z", 0.96, 0.97, size=1.0),
        book("polymarket_us", "aec-test-a-b", f"{day}T12:00:01Z", 0.98, 0.99, size=1.0),
        book("kalshi", "KXTEST-26OCT10-A", f"{day}T12:00:03Z", 0.96, 0.97, size=1.0),
    ]
    name = f"thin-{day}.jsonl"
    (tmp_path / name).write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    r.sidecar(tmp_path / name).write_text(json.dumps(MATCH))
    (tmp_path / name).with_suffix(".meta.json").write_text(json.dumps({"sizes_unknown": True}))
    return name


def test_a_real_one_cent_gap_survives_at_the_assumed_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    from uselayer import FeeSettings, calculate_fee
    from uselayer.fees import dollars

    monkeypatch.setattr(r, "RECORDINGS", tmp_path)
    name = thin_gap(tmp_path)
    at = datetime(2026, 10, 10, 12, tzinfo=UTC)
    k_fee = dollars(calculate_fee(FeeSettings(venue="kalshi"), contracts=1, price=0.97, role="taker", at=at))
    assert k_fee == 0.01  # Kalshi rounds a 0.2¢ fee up to 1¢ on one contract: the whole gap

    one = r.replay(name, ScanSettings(size=1))["best_survivor"]["quote"]
    assert one["net_profit"] == 0.0  # why one contract was the wrong default

    out = r.replay(name, ScanSettings(size=100))
    q = out["best_survivor"]["quote"]
    assert q["contracts"] == 100 and q["gross_spread"] == pytest.approx(1.0)
    k100 = dollars(calculate_fee(FeeSettings(venue="kalshi"), contracts=100, price=0.97, role="taker", at=at))
    assert q["a"]["fee"] == k100  # the SDK's own fee, rounded per order
    assert q["net_profit"] > 0.5
    assert 0 < q["edge_at_best"] < q["gross_at_best"]  # per contract, fees before rounding


def test_assume_size_applies_level_changes_and_keeps_the_top_price_only() -> None:
    from datetime import UTC, datetime

    from uselayer import Book, BookLevelChange, Level

    t0, t1 = datetime(2026, 10, 10, 12, tzinfo=UTC), datetime(2026, 10, 10, 12, 0, 2, tzinfo=UTC)
    full = Book(venue="kalshi", market="K", bids=[Level(price=0.4, size=1), Level(price=0.39, size=1)], asks=[Level(price=0.42, size=1), Level(price=0.45, size=1)], as_of=t0)
    better = BookLevelChange(venue="kalshi", market="K", book_side="ask", price=0.41, size=1, as_of=t1)
    other = Book(venue="kalshi", market="X", bids=[Level(price=0.1, size=7)], asks=[], as_of=t0)
    out = r.assume_size([full, better, other], {("kalshi", "K")}, 50)
    books = [b for b in out if b.market == "K"]
    assert [(b.asks[0].price, b.asks[0].size, len(b.asks), b.bids[0].size) for b in books] == [(0.42, 50, 1, 50), (0.41, 50, 1, 50)]
    assert other in out  # markets outside the pair pass through untouched


def test_before_the_fee_schedule_says_so_in_one_sentence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "RECORDINGS", tmp_path)
    name = thin_gap(tmp_path, day="2025-10-20")  # the SDK's Polymarket US fees start Nov 3, 2025 (Kalshi's Oct 1)
    with pytest.raises(r.CannotPrice) as e:
        r.replay(name, ScanSettings(size=100))
    assert str(e.value) == (
        "Can't replay this file: it's from before Nov 3, 2025, and the SDK doesn't have Polymarket US's fees from before then yet."
    )


def test_a_pair_worded_differently_is_replayed_with_its_warning(recording: str, tmp_path: Path) -> None:
    r.sidecar(tmp_path / recording).write_text(json.dumps(MATCH | {"caveats": ["source_differs"]}))
    out = r.replay(recording, ScanSettings(size=10))
    assert out["counts"]["survivor"] >= 1
    assert out["match"]["rule_warning"].startswith("Worded differently: different data source.")


def test_no_pair_in_the_file_is_one_sentence(recording: str, tmp_path: Path) -> None:
    (tmp_path / "lonely.jsonl").write_text((tmp_path / recording).read_text().splitlines()[0] + "\n")
    with pytest.raises(LookupError) as e:
        r.replay("lonely.jsonl", ScanSettings(), lookup=lambda t: None)
    assert str(e.value) == "Can't replay this file: it doesn't hold a Kalshi market and its Polymarket US match together."


def test_a_file_from_before_sep_25_now_replays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # uselayer 0.4.1 has Polymarket US's fees back to Nov 3, 2025: a July file is priced like any other.
    monkeypatch.setattr(r, "RECORDINGS", tmp_path)
    out = r.replay(thin_gap(tmp_path, day="2026-07-22"), ScanSettings(size=100))
    assert out["counts"]["survivor"] >= 1


def test_a_payout_time_already_past_is_left_out_not_a_dead_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A season-long market whose venue gives the season's start as its event time: the estimated
    # payout (start + 6 h) is before the recording. Each moment is still priced, with no return per day.
    monkeypatch.setattr(r, "RECORDINGS", tmp_path)
    name = thin_gap(tmp_path)
    (tmp_path / name).with_suffix(".meta.json").write_text(json.dumps({"sizes_unknown": True, "settles_at": "2026-08-29T01:00:00Z"}))
    out = r.replay(name, ScanSettings(size=100))
    assert out["moments"] >= 1 and out["counts"]["survivor"] >= 1
    assert out["best_survivor"]["quote"]["return_per_day_pct"] is None


def test_a_file_never_priced_on_both_venues_is_one_sentence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "RECORDINGS", tmp_path)
    lines = [book("kalshi", "KXTEST-26OCT10-A", "2026-10-10T12:00:00Z", 0.4, 0.42), book("kalshi", "KXTEST-26OCT10-A", "2026-10-10T12:00:05Z", 0.4, 0.42)]
    (tmp_path / "one-leg.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    r.sidecar(tmp_path / "one-leg.jsonl").write_text(json.dumps(MATCH))
    with pytest.raises(r.CannotPrice) as e:
        r.replay("one-leg.jsonl", ScanSettings())
    assert str(e.value) == "Can't replay this file: it never has prices on both venues at the same moment."


def test_only_files_inside_recordings(recording: str) -> None:
    with pytest.raises(FileNotFoundError):
        r.replay("../../etc/passwd", ScanSettings())


def test_payout_rule() -> None:
    from uselayer import Match

    at = r.payout_at(Match.model_validate(MATCH))
    assert at is not None and at.isoformat() == "2026-10-11T02:00:00+00:00"  # later event + 6 h, before the close


def test_layer_with_no_twin_is_not_found_not_a_crash() -> None:
    from uselayer import VenueError

    class _C:
        def match(self, ticker, *, venue, with_):  # noqa: ANN001, ANN202
            return {"source_market": {"venue": "kalshi", "market_id": ticker}, "matched_market": None}

    with pytest.raises(VenueError) as e:
        r.layer_match(_C(), "KXNOSUCH-1")  # type: ignore[arg-type]
    assert e.value.code == "not_found"
