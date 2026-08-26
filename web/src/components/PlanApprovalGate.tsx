/**
 * Human-in-the-Loop Approval Gate Component.
 *
 * Core Workflow:
 *   - The agent has drafted a research plan during Phase 1 and paused execution in `awaiting_approval`.
 *   - The user reviews, reorders, edits, adds, or deletes steps.
 *   - User clarification answers are gathered for any optional questions formulated by the model.
 *   - A dynamic `CostEstimate` preview re-prices the plan in real-time as steps change.
 *   - Clicking "Approve Plan & Launch Research" sends the approved steps and answers to `/api/tasks/{task_id}/approve`.
 *   - Backend arbitrates concurrency atomically using conditional SQL updates, preventing duplicate runs.
 */
"use client";

import React, { useState } from "react";
import { formatUsd, TaskDetail } from "@/lib/api";
import { CostEstimate } from "@/components/CostEstimate";

/** Props for PlanApprovalGate component */
interface PlanApprovalGateProps {
  /** Detailed task object currently awaiting approval */
  task: TaskDetail;
  /** Async callback to approve edited plan and clarification answers */
  onApprove: (plan: string[], answers: Record<string, string>) => Promise<void>;
  /** Async callback to cancel the task */
  onCancel: () => Promise<void>;
  /** Whether an approval or cancellation request is in flight */
  loading: boolean;
}

/**
 * Renders the human approval gate interface with step editor and pricing preview.
 */
export function PlanApprovalGate({
  task,
  onApprove,
  onCancel,
  loading,
}: PlanApprovalGateProps) {
  const initialPlan = task.plan && task.plan.length > 0 ? task.plan : [task.query];
  const [steps, setSteps] = useState<string[]>(initialPlan);
  const [newStepText, setNewStepText] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});

  // Local edits only. Nothing is sent until Approve, so the person can rewrite
  // the plan freely without triggering work or partial saves.
  const handleStepChange = (index: number, value: string) => {
    const updated = [...steps];
    updated[index] = value;
    setSteps(updated);
  };

  const handleRemoveStep = (index: number) => {
    if (steps.length <= 1) return;
    setSteps(steps.filter((_, i) => i !== index));
  };

  const handleMoveStep = (index: number, direction: "up" | "down") => {
    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= steps.length) return;
    const updated = [...steps];
    const [moved] = updated.splice(index, 1);
    updated.splice(targetIndex, 0, moved);
    setSteps(updated);
  };

  const handleAddStep = () => {
    if (!newStepText.trim()) return;
    setSteps([...steps, newStepText.trim()]);
    setNewStepText("");
  };

  const handleAnswerChange = (question: string, val: string) => {
    setAnswers((prev) => ({ ...prev, [question]: val }));
  };

  const handleApprove = async () => {
    // Blank steps are dropped rather than rejected - an empty row is a slip,
    // not an instruction, and the API would refuse the whole plan for one.
    const cleanSteps = steps.map((s) => s.trim()).filter(Boolean);
    if (cleanSteps.length === 0) return;
    await onApprove(cleanSteps, answers);
  };

  return (
    <div className="w-full max-w-4xl mx-auto py-8 px-4">
      {/* Human Gate Banner */}
      <div className="mb-6 p-4 rounded-2xl bg-amber-950/40 border border-amber-800/60 flex items-start gap-3.5">
        <div className="p-2 rounded-xl bg-amber-500/10 text-amber-400 font-bold">
          🛡️
        </div>
        <div>
          <h2 className="text-sm font-semibold text-amber-200">
            Human Approval Gate Active
          </h2>
          <p className="text-xs text-amber-300/80 mt-0.5">
            The agent has drafted a research plan. You can edit the steps, add clarifications, or remove unwanted directions. No web searches will run until you approve.
          </p>
        </div>
      </div>

      {/* Query summary */}
      <div className="mb-6 p-5 rounded-2xl bg-zinc-900 border border-zinc-800">
        <div className="text-[11px] uppercase font-bold tracking-wider text-zinc-500 mb-1">
          Research Query
        </div>
        <div className="text-base font-medium text-zinc-100">{task.query}</div>
        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-zinc-400 pt-3 border-t border-zinc-800/80">
          <span>
            Provider:{" "}
            <strong className="text-zinc-200 font-mono">
              {task.provider || "Anthropic"} / {task.model || "Opus 5"}
            </strong>
          </span>
          <span>
            Spent so far:{" "}
            <strong className="text-zinc-200 font-mono">
              {formatUsd(task.actual_cost_usd)}
            </strong>{" "}
            <span className="text-zinc-500">
              ({task.input_tokens + task.output_tokens} tokens drafting this plan)
            </span>
          </span>
        </div>
      </div>

      {/* Clarifying Questions (if any) */}
      {task.clarifying_questions && task.clarifying_questions.length > 0 && (
        <div className="mb-6 p-5 rounded-2xl bg-zinc-900 border border-zinc-800">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-semibold text-zinc-200">
              Clarifying Questions
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">
              Optional
            </span>
          </div>
          <div className="space-y-4">
            {task.clarifying_questions.map((q, idx) => (
              <div key={idx} className="space-y-1.5">
                <label className="block text-xs font-medium text-zinc-300">
                  {idx + 1}. {q}
                </label>
                <input
                  type="text"
                  value={answers[q] || ""}
                  onChange={(e) => handleAnswerChange(q, e.target.value)}
                  placeholder="Your clarification or specific focus..."
                  className="w-full px-3.5 py-2 bg-zinc-950 border border-zinc-800 rounded-xl text-xs text-zinc-100 placeholder-zinc-500 focus:outline-hidden focus:border-indigo-500 transition-colors"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* What approving this will cost - the decision the gate actually asks for */}
      <CostEstimate taskId={task.id} plan={steps} />

      {/* Plan Step Editor */}
      <div className="mb-8 p-5 rounded-2xl bg-zinc-900 border border-zinc-800">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-zinc-200">
              Review & Edit Research Plan
            </h3>
            <p className="text-xs text-zinc-400">
              Reorder, edit, add, or delete steps before research commences.
            </p>
          </div>
          <span className="text-xs font-mono text-indigo-400 bg-indigo-950/60 px-2 py-1 rounded-md border border-indigo-800/40">
            {steps.length} Steps
          </span>
        </div>

        <div className="space-y-2.5 mb-4">
          {steps.map((step, idx) => (
            <div
              key={idx}
              className="flex items-center gap-2 p-2.5 bg-zinc-950 border border-zinc-800/90 rounded-xl group hover:border-zinc-700 transition-colors"
            >
              <span className="h-6 w-6 shrink-0 rounded-lg bg-zinc-800 text-zinc-300 text-xs font-mono font-bold flex items-center justify-center">
                {idx + 1}
              </span>
              <input
                type="text"
                value={step}
                onChange={(e) => handleStepChange(idx, e.target.value)}
                className="flex-1 bg-transparent text-xs text-zinc-200 focus:outline-hidden"
              />
              <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
                <button
                  type="button"
                  disabled={idx === 0}
                  onClick={() => handleMoveStep(idx, "up")}
                  className="p-1 text-zinc-400 hover:text-zinc-200 disabled:opacity-20 hover:bg-zinc-800 rounded cursor-pointer"
                  title="Move step up"
                >
                  ▲
                </button>
                <button
                  type="button"
                  disabled={idx === steps.length - 1}
                  onClick={() => handleMoveStep(idx, "down")}
                  className="p-1 text-zinc-400 hover:text-zinc-200 disabled:opacity-20 hover:bg-zinc-800 rounded cursor-pointer"
                  title="Move step down"
                >
                  ▼
                </button>
                <button
                  type="button"
                  disabled={steps.length <= 1}
                  onClick={() => handleRemoveStep(idx)}
                  className="p-1 text-red-400 hover:text-red-300 disabled:opacity-20 hover:bg-red-950/50 rounded cursor-pointer"
                  title="Delete step"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Add Step */}
        <div className="flex items-center gap-2 pt-2 border-t border-zinc-800/80">
          <input
            type="text"
            value={newStepText}
            onChange={(e) => setNewStepText(e.target.value)}
            placeholder="Add a new custom research step..."
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleAddStep();
              }
            }}
            className="flex-1 px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-xl text-xs text-zinc-100 placeholder-zinc-500 focus:outline-hidden focus:border-indigo-500"
          />
          <button
            type="button"
            onClick={handleAddStep}
            disabled={!newStepText.trim()}
            className="px-3 py-2 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-zinc-200 text-xs font-medium rounded-xl transition-colors cursor-pointer"
          >
            + Add Step
          </button>
        </div>
      </div>

      {/* Action Footer */}
      <div className="flex items-center justify-between gap-4 p-4 rounded-2xl bg-zinc-900 border border-zinc-800">
        <button
          type="button"
          onClick={onCancel}
          disabled={loading}
          className="px-4 py-2.5 text-xs font-semibold text-zinc-400 hover:text-red-400 hover:bg-red-950/30 rounded-xl border border-transparent hover:border-red-900/50 transition-all cursor-pointer"
        >
          Cancel Task
        </button>

        <button
          type="button"
          onClick={handleApprove}
          disabled={loading || steps.length === 0}
          className="inline-flex items-center gap-2 px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-bold rounded-xl shadow-lg shadow-emerald-950 transition-all cursor-pointer"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Launching Agent...
            </>
          ) : (
            <>
              Approve Plan & Launch Research
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </>
          )}
        </button>
      </div>
    </div>
  );
}

