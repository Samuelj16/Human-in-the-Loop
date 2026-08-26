import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PlanApprovalGate } from "@/components/PlanApprovalGate";
import type { TaskDetail } from "@/lib/api";

// The gate embeds a live pricer that fetches on mount. Stub it out: what this
// suite pins down is what the gate *sends*, not what the estimate renders.
vi.mock("@/components/CostEstimate", () => ({
  CostEstimate: () => null,
}));

function task(over: Partial<TaskDetail> = {}): TaskDetail {
  return {
    id: "task-1",
    query: "How many EVs shipped in 2025?",
    status: "awaiting_approval",
    created_at: "2026-01-01T00:00:00Z",
    plan: ["Find shipment totals", "Cross-check against registrations"],
    plan_edited_by_user: false,
    is_public: false,
    input_tokens: 1200,
    output_tokens: 300,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    searches_used: 0,
    actual_cost_usd: 0.012,
    events: [],
    sources: [],
    ...over,
  };
}

/**
  * The step rows are the only text inputs without a placeholder - the composer
  * and the clarification fields both have one. Selecting on placeholder rather
  * than on value keeps the indices stable when a test clears a row.
  */
function stepInputs(): HTMLInputElement[] {
  return screen
    .getAllByRole("textbox")
    .filter((el): el is HTMLInputElement => !(el as HTMLInputElement).placeholder);
}

/** Matches in both states: the label flips to "Launching Agent..." while loading. */
function approveButton() {
  return screen.getByRole("button", { name: /approve plan|launching agent/i });
}

describe("PlanApprovalGate", () => {
  it("seeds the editor from the drafted plan", () => {
    render(
      <PlanApprovalGate task={task()} onApprove={vi.fn()} onCancel={vi.fn()} loading={false} />,
    );
    expect(stepInputs().map((i) => i.value)).toEqual([
      "Find shipment totals",
      "Cross-check against registrations",
    ]);
    expect(screen.getByText("2 Steps")).toBeInTheDocument();
  });

  it("falls back to the raw query when the model returned no plan", () => {
    render(
      <PlanApprovalGate
        task={task({ plan: null })}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
        loading={false}
      />,
    );
    expect(stepInputs().map((i) => i.value)).toEqual(["How many EVs shipped in 2025?"]);
  });

  it("sends the user's edits, not the model's original plan", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <PlanApprovalGate task={task()} onApprove={onApprove} onCancel={vi.fn()} loading={false} />,
    );

    await user.clear(stepInputs()[0]);
    await user.type(stepInputs()[0], "Find shipment totals for China only");
    await user.click(approveButton());

    expect(onApprove).toHaveBeenCalledWith(
      ["Find shipment totals for China only", "Cross-check against registrations"],
      {},
    );
  });

  it("reorders steps and approves in the new order", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <PlanApprovalGate task={task()} onApprove={onApprove} onCancel={vi.fn()} loading={false} />,
    );

    await user.click(screen.getAllByTitle("Move step down")[0]);
    await user.click(approveButton());

    expect(onApprove).toHaveBeenCalledWith(
      ["Cross-check against registrations", "Find shipment totals"],
      {},
    );
  });

  it("disables the move controls at the ends of the list", () => {
    render(
      <PlanApprovalGate task={task()} onApprove={vi.fn()} onCancel={vi.fn()} loading={false} />,
    );
    expect(screen.getAllByTitle("Move step up")[0]).toBeDisabled();
    const downs = screen.getAllByTitle("Move step down");
    expect(downs[downs.length - 1]).toBeDisabled();
  });

  it("adds a step and clears the composer", async () => {
    const user = userEvent.setup();
    render(
      <PlanApprovalGate task={task()} onApprove={vi.fn()} onCancel={vi.fn()} loading={false} />,
    );

    const composer = screen.getByPlaceholderText(/add a new custom research step/i);
    await user.type(composer, "Check manufacturer press releases");
    await user.click(screen.getByRole("button", { name: /add step/i }));

    expect(stepInputs()).toHaveLength(3);
    expect(screen.getByText("3 Steps")).toBeInTheDocument();
    expect(composer).toHaveValue("");
  });

  it("refuses to add a whitespace-only step", async () => {
    const user = userEvent.setup();
    render(
      <PlanApprovalGate task={task()} onApprove={vi.fn()} onCancel={vi.fn()} loading={false} />,
    );
    await user.type(screen.getByPlaceholderText(/add a new custom research step/i), "   ");
    expect(screen.getByRole("button", { name: /add step/i })).toBeDisabled();
  });

  it("deletes a step, and will not delete the last one", async () => {
    const user = userEvent.setup();
    render(
      <PlanApprovalGate task={task()} onApprove={vi.fn()} onCancel={vi.fn()} loading={false} />,
    );

    await user.click(screen.getAllByTitle("Delete step")[0]);
    expect(stepInputs().map((i) => i.value)).toEqual(["Cross-check against registrations"]);
    // One step left: deleting it would send an empty plan, which the API rejects.
    expect(screen.getByTitle("Delete step")).toBeDisabled();
  });

  it("drops blanked-out rows instead of sending an invalid plan", async () => {
    // The API 400s on a plan containing an empty step, so a row the person
    // cleared but did not delete must not sink the whole approval.
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <PlanApprovalGate task={task()} onApprove={onApprove} onCancel={vi.fn()} loading={false} />,
    );

    await user.clear(stepInputs()[0]);
    await user.click(approveButton());

    expect(onApprove).toHaveBeenCalledWith(["Cross-check against registrations"], {});
  });

  it("passes clarification answers through, keyed by question", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <PlanApprovalGate
        task={task({ clarifying_questions: ["Which region?", "Which year?"] })}
        onApprove={onApprove}
        onCancel={vi.fn()}
        loading={false}
      />,
    );

    // NOTE: the component renders <label> with no htmlFor and the input as a
    // sibling, so getByLabelText cannot reach it. Selecting by position instead
    // and leaving the a11y gap recorded here rather than silently worked around.
    const clarificationInputs = screen.getAllByPlaceholderText(
      /your clarification or specific focus/i,
    );
    expect(clarificationInputs).toHaveLength(2);
    await user.type(clarificationInputs[0], "China");
    await user.click(approveButton());

    expect(onApprove).toHaveBeenCalledWith(expect.any(Array), { "Which region?": "China" });
  });

  it("does not fire approval while a request is already in flight", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <PlanApprovalGate task={task()} onApprove={onApprove} onCancel={vi.fn()} loading={true} />,
    );

    expect(approveButton()).toBeDisabled();
    await user.click(approveButton());
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("cancels the task without touching the approval path", async () => {
    const onApprove = vi.fn();
    const onCancel = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <PlanApprovalGate task={task()} onApprove={onApprove} onCancel={onCancel} loading={false} />,
    );

    await user.click(screen.getByRole("button", { name: /cancel task/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onApprove).not.toHaveBeenCalled();
  });
});
