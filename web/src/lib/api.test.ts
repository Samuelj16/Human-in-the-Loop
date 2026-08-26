import { describe, expect, it } from "vitest";
import { ApiError, errorMessage, formatUsd, TERMINAL_STATUSES } from "@/lib/api";

describe("formatUsd", () => {
  it("renders an em dash for a missing amount", () => {
    expect(formatUsd(null)).toBe("—");
    expect(formatUsd(undefined)).toBe("—");
  });

  it("distinguishes a genuine zero from a sub-cent amount", () => {
    // A run that spent nothing and a run that spent a fraction of a cent are
    // different facts; collapsing both to $0.00 would hide real spend.
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(0.004)).toBe("<$0.01");
  });

  it("rounds to two decimals above a cent", () => {
    expect(formatUsd(0.01)).toBe("$0.01");
    expect(formatUsd(0.0099)).toBe("<$0.01");
    expect(formatUsd(1.25)).toBe("$1.25");
    expect(formatUsd(1.239)).toBe("$1.24");
    expect(formatUsd(25.5)).toBe("$25.50");
    expect(formatUsd(100)).toBe("$100.00");
  });
});

describe("errorMessage", () => {
  it("prefers the thrown Error's message", () => {
    expect(errorMessage(new Error("quota exceeded"), "fallback")).toBe("quota exceeded");
  });

  it("falls back when the value is not an Error or carries no message", () => {
    expect(errorMessage(new Error(""), "fallback")).toBe("fallback");
    expect(errorMessage("a bare string", "fallback")).toBe("fallback");
    expect(errorMessage(null, "fallback")).toBe("fallback");
    expect(errorMessage(undefined, "fallback")).toBe("fallback");
    expect(errorMessage({ code: 500 }, "fallback")).toBe("fallback");
  });

  it("reads the message off an ApiError subclass", () => {
    expect(errorMessage(new ApiError("Task not found", 404), "fallback")).toBe(
      "Task not found",
    );
  });
});

describe("ApiError", () => {
  it("keeps the HTTP status so callers can branch on 409 vs 404", () => {
    const err = new ApiError("Plan already approved", 409);
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe("Plan already approved");
    expect(err.name).toBe("ApiError");
    expect(err.status).toBe(409);
  });

  it("preserves rate-limit and server statuses too", () => {
    expect(new ApiError("Too Many Requests", 429).status).toBe(429);
    expect(new ApiError("Internal Server Error", 500).status).toBe(500);
  });
});

describe("TERMINAL_STATUSES", () => {
  it("covers exactly the states where polling must stop", () => {
    expect(TERMINAL_STATUSES).toEqual(["complete", "failed", "cancelled"]);
  });

  it("excludes every in-flight state - the gate is a pause, not an ending", () => {
    for (const live of ["queued", "planning", "awaiting_approval", "researching"] as const) {
      expect(TERMINAL_STATUSES).not.toContain(live);
    }
  });
});
