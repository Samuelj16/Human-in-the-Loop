/** Displays citation coverage and source-quality checks for a completed report. */
"use client";

import { CitationReport } from "@/lib/api";

/**
 * Shows how the report's citations fared against the retrieval ledger.
 *
 * Every URL a search actually returned is recorded server-side. Anything the
 * report cites that is missing from that ledger was produced from the model's
 * memory rather than from evidence it read - so it gets called out here instead
 * of sitting in the text looking exactly as authoritative as a real source.
 */
export function CitationAudit({ report }: { report: CitationReport }) {
  const { cited_count, verified_count, unverified, unused_count, is_clean } = report;

  if (cited_count === 0) {
    return (
      <div className="mb-6 p-4 rounded-2xl bg-zinc-900 border border-zinc-800 text-xs text-zinc-400">
        This report cites no links, so there was nothing to verify.
        {unused_count > 0 && (
          <> {unused_count} retrieved source(s) went unused.</>
        )}
      </div>
    );
  }

  return (
    <div
      className={`mb-6 p-5 rounded-2xl border ${
        is_clean
          ? "bg-emerald-950/25 border-emerald-800/50"
          : "bg-red-950/30 border-red-800/60"
      }`}
    >
      <div className="flex items-start gap-3">
        <span className="text-lg leading-none mt-0.5">{is_clean ? "✓" : "⚠"}</span>
        <div className="flex-1">
          <h3
            className={`text-sm font-semibold ${
              is_clean ? "text-emerald-200" : "text-red-200"
            }`}
          >
            {is_clean
              ? `All ${cited_count} cited link${cited_count === 1 ? "" : "s"} verified`
              : `${unverified.length} of ${cited_count} cited links could not be verified`}
          </h3>
          <p
            className={`text-xs mt-1 leading-relaxed ${
              is_clean ? "text-emerald-400/80" : "text-red-300/80"
            }`}
          >
            {is_clean ? (
              <>
                Every URL in this report appears in the retrieval ledger — the
                agent actually fetched each one during the run.
              </>
            ) : (
              <>
                The links below appear in the report but were never returned by
                any search the agent ran. Treat them as unsourced claims and
                check them yourself before relying on them.
              </>
            )}
          </p>

          {unverified.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {unverified.map((url) => (
                <li
                  key={url}
                  className="text-[11px] font-mono text-red-300 bg-red-950/40 border border-red-900/50 rounded-lg px-2.5 py-1.5 break-all"
                >
                  {url}
                </li>
              ))}
            </ul>
          )}

          <div
            className={`mt-3 pt-3 border-t flex flex-wrap gap-4 text-[11px] ${
              is_clean
                ? "border-emerald-900/50 text-emerald-400/70"
                : "border-red-900/50 text-red-300/70"
            }`}
          >
            <span>
              Verified{" "}
              <strong className="font-mono tabular-nums">
                {verified_count}/{cited_count}
              </strong>
            </span>
            <span>
              Retrieved but uncited{" "}
              <strong className="font-mono tabular-nums">{unused_count}</strong>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
