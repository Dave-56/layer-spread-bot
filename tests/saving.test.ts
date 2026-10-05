import { describe, expect, it } from "vitest";
import { clock, LENGTHS, savedLine, savingLine } from "@/components/saving";

describe("Save prices", () => {
  it("counts time down as minutes and seconds, hours when there are any", () => {
    expect(clock(1800)).toBe("30:00");
    expect(clock(65)).toBe("1:05");
    expect(clock(3725)).toBe("1:02:05");
    expect(clock(-3)).toBe("0:00");
  });

  it("shows time left and what's saved while it runs", () => {
    expect(savingLine({ events: 1234 }, 754)).toBe("12:34 left · 1,234 price updates saved");
    expect(savingLine({ events: 1 }, 59.6)).toBe("1:00 left · 1 price update saved");
  });

  it("points at Replay once saved, stopped early or not", () => {
    for (const state of ["done", "stopped"] as const) {
      expect(savedLine({ state, events: 412, error: null })).toBe("Saved 412 price updates. It's selected under Saved prices: press Replay.");
    }
    expect(savedLine({ state: "recording", events: 3, error: null })).toBeNull();
  });

  it("says the engine's one sentence when it failed", () => {
    const error = "Nothing was saved: neither venue sent a price while recording.";
    expect(savedLine({ state: "failed", events: 0, error })).toBe(error);
  });

  it("offers 30 minutes, the default, among the lengths", () => {
    expect(LENGTHS.map((l) => l.minutes)).toContain(30);
  });
});
