/**
 * Frontend Unit Test Suite (`web/tests/api.test.ts`).
 *
 * Tests utility functions, formatting helpers, error wrappers, and state machine constants.
 */
import test, { describe } from "node:test";
import assert from "node:assert/strict";

import {
  ApiError,
  errorMessage,
  formatUsd,
  TERMINAL_STATUSES,
} from "../src/lib/api.ts";

describe("Frontend API Client & Utilities", () => {
  describe("formatUsd", () => {
    test("formats standard dollar amounts with 2 decimals", () => {
      assert.equal(formatUsd(1.25), "$1.25");
      assert.equal(formatUsd(25.5), "$25.50");
      assert.equal(formatUsd(100), "$100.00");
    });

    test("formats exact zero as $0.00", () => {
      assert.equal(formatUsd(0), "$0.00");
    });

    test("formats sub-cent amounts as <$0.01", () => {
      assert.equal(formatUsd(0.0042), "<$0.01");
      assert.equal(formatUsd(0.0001), "<$0.01");
      assert.equal(formatUsd(0.0099), "<$0.01");
    });

    test("handles null and undefined with an em-dash placeholder", () => {
      assert.equal(formatUsd(null), "—");
      assert.equal(formatUsd(undefined), "—");
    });
  });

  describe("errorMessage", () => {
    test("extracts message from standard Error instance", () => {
      const err = new Error("Network connection dropped");
      assert.equal(errorMessage(err, "Fallback"), "Network connection dropped");
    });

    test("returns fallback string when error is not an Error instance", () => {
      assert.equal(errorMessage("just a string", "Default Error"), "Default Error");
      assert.equal(errorMessage(null, "Default Error"), "Default Error");
      assert.equal(errorMessage(undefined, "Default Error"), "Default Error");
      assert.equal(errorMessage({ code: 500 }, "Default Error"), "Default Error");
    });

    test("returns fallback string when Error instance has empty message", () => {
      const err = new Error("");
      assert.equal(errorMessage(err, "Default Fallback"), "Default Fallback");
    });
  });

  describe("ApiError", () => {
    test("instantiates with custom message, name, and HTTP status code", () => {
      const err = new ApiError("Task not found", 404);
      assert.equal(err.message, "Task not found");
      assert.equal(err.status, 404);
      assert.equal(err.name, "ApiError");
      assert.ok(err instanceof Error);
    });

    test("preserves status code for rate limit and server errors", () => {
      const rateLimitErr = new ApiError("Too Many Requests", 429);
      assert.equal(rateLimitErr.status, 429);

      const serverErr = new ApiError("Internal Server Error", 500);
      assert.equal(serverErr.status, 500);
    });
  });

  describe("TERMINAL_STATUSES", () => {
    test("contains all terminal research task lifecycle states", () => {
      assert.deepEqual(TERMINAL_STATUSES, ["complete", "failed", "cancelled"]);
    });

    test("does not include active in-flight states", () => {
      assert.ok(!TERMINAL_STATUSES.includes("queued" as any));
      assert.ok(!TERMINAL_STATUSES.includes("planning" as any));
      assert.ok(!TERMINAL_STATUSES.includes("awaiting_approval" as any));
      assert.ok(!TERMINAL_STATUSES.includes("researching" as any));
    });
  });
});
