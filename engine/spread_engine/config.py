"""Settings, read once from the repo's .env file (and the environment).

Keys stay on this machine: the SDK reads them from the environment and uses them only to talk to
each venue as you. They are never logged, never returned by the engine's API and never sent to
Layer. Layer gets only your Layer API key and the market ids it gave you.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

# The repo's .env (or .env.local) fills in anything not already in the environment.
for name in (".env.local", ".env"):
    load_dotenv(ROOT / name, override=False)


@dataclass(frozen=True)
class Settings:
    mode: str  # "paper" (default) or "live"
    budget: float  # $ at risk across everything at once (the SDK's budget guardrail)
    # The bot's own store (default ~/.uselayer/spread-bot/), kept apart from any other uselayer use on
    # this machine, so resetting the paper account touches only the bot's fake trades.
    store_dir: Path
    # Paper only: seconds from sending an order to it reaching the book (the SDK's order_latency_s).
    # The order fills against the book it meets then, not the one it was priced on. Default 0.7 s, the
    # median the SDK measured on Polymarket US (0.6-1.4 s over 8 orders). 0 fills instantly.
    order_latency_s: float = 0.7

    @property
    def store(self) -> Path:
        return self.store_dir / f"{self.mode}.db"

    @property
    def keys(self) -> dict[str, bool]:
        """Which keys are set. Only yes/no: the values never leave this process."""
        return {
            "layer": bool(os.environ.get("LAYER_API_KEY")),
            "kalshi": bool(
                os.environ.get("KALSHI_KEY_ID")
                and (os.environ.get("KALSHI_PRIVATE_KEY_PATH") or os.environ.get("KALSHI_PRIVATE_KEY"))
            ),
            "polymarket_us": bool(
                os.environ.get("POLYMARKET_US_KEY_ID") and os.environ.get("POLYMARKET_US_SECRET_KEY")
            ),
        }


def load() -> Settings:
    # Live is opt-in: only the exact word "live" turns it on. Anything else is paper.
    mode = "live" if os.environ.get("BOT_MODE", "paper").strip().lower() == "live" else "paper"
    budget = float(os.environ.get("BOT_BUDGET", "100"))
    store_dir = Path(os.environ.get("BOT_STORE_DIR") or "~/.uselayer/spread-bot").expanduser()
    latency = float(os.environ.get("BOT_ORDER_LATENCY_S", "0.7"))
    return Settings(mode=mode, budget=budget, store_dir=store_dir, order_latency_s=latency)
