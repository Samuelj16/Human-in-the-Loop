/**
 * Cost Estimate Component: pre-flight dollar pricing preview on the human approval gate.
 *
 * Design & Economics:
 *   - An approval screen that only asks "does this look right?" is a rubber stamp.
 *   - Showing calculated dollar costs turns human approval into an active business decision.
 *   - The estimate dynamically recomputes as steps are added, edited, or removed.
 *   - Displays expected, low, and high cost ranges, projected searches, turn counts, and model ID.
 */
"use client";

import { useEffect, useState } from "react";

import { api, CostEstimate as Estimate, formatUsd } from "@/lib/api";

/** Props for CostEstimate component */
interface CostEstimateProps {
  /** Research task ID */
  taskId: string;
  /** The plan steps list as currently edited by the user in the UI */
  plan: string[];
}

/**
 * Renders the dollar cost estimate card with search counts and price ranges.
 */
export function CostEstimate({ taskId, plan }: CostEstimateProps) {
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Cost depends on the number of steps, not their wording, so this refetches
  // when steps are added or removed rather than on every keystroke.
  const stepCount = plan.length;

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const next = await api.tasks.estimateFor(taskId, plan);
        if (!cancelled) {
          setEstimate(next);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Estimate unavailable");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, stepCount]);

  if (error) {
    return (
      <div className="mb-6 p-4 rounded-2xl bg-zinc-900 border border-zinc-800 text-xs text-zinc-400">
        Cost estimate unavailable ({error}). The spend caps still apply.
      </div>
    );
  }

  return (
    <div className="mb-6 p-5 rounded-2xl bg-emerald-950/30 border border-emerald-800/50">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase font-bold tracking-wider text-emerald-500/90">
            Estimated cost to run this plan
          </div>
          <div className="mt-1 flex items-baseline gap-2.5">
            <span className="text-3xl font-semibold text-emerald-200 tabular-nums">
              {estimate ? formatUsd(estimate.expected_usd) : "…"}
            </span>
            {estimate && (
              <span className="text-xs text-emerald-400/70 tabular-nums">
                range {formatUsd(estimate.low_usd)}–{formatUsd(estimate.high_usd)}
              </span>
            )}
          </div>
        </div>

        {estimate && (
          <dl className="flex gap-6 text-xs">
            <div>
              <dt className="text-emerald-500/70">Searches</dt>
              <dd className="text-emerald-200 font-mono tabular-nums">
                ~{estimate.expected_searches}
              </dd>
            </div>
            <div>
              <dt className="text-emerald-500/70">Model turns</dt>
              <dd className="text-emerald-200 font-mono tabular-nums">
                ~{estimate.expected_turns}
              </dd>
            </div>
            <div>
              <dt className="text-emerald-500/70">Model</dt>
              <dd className="text-emerald-200 font-mono">{estimate.model}</dd>
            </div>
          </dl>
        )}
      </div>

      <p className="mt-3 pt-3 border-t border-emerald-900/50 text-[11px] leading-relaxed text-emerald-400/70">
        {estimate && !estimate.priced ? (
          <>
            No published price is configured for this model, so this figure is a
            placeholder — set OPENAI_PRICE_INPUT / OPENAI_PRICE_OUTPUT for a real
            number. Adding or removing steps changes the estimate.
          </>
        ) : (
          <>
            Based on list prices, assuming prompt caching. Hard caps stop the run
            at the top of the range even if the agent wants to keep going.
          </>
        )}
      </p>
    </div>
  );
}

