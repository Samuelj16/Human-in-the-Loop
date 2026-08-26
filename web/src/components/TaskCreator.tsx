/**
 * The entry point: where a research question is written.
 *
 * Submitting does not start any research - it starts *planning*, which stops at
 * the approval gate. Nothing is spent until the person approves the plan there.
 */
"use client";

import React, { useState } from "react";

interface TaskCreatorProps {
  onSubmit: (query: string) => Promise<void>;
  loading: boolean;
}

const SAMPLE_PROMPTS = [
  "Current state of solid-state battery commercial readiness and production timelines (2026)",
  "Comparative analysis of Post-Quantum Cryptography standards: ML-KEM vs SLH-DSA adoption",
  "Small Modular Nuclear Reactors (SMRs): regulatory approvals, LCOE economics, and pilot sites",
  "Breakthroughs in non-invasive neural interface bandwidth and clinical trial status",
];

export function TaskCreator({ onSubmit, loading }: TaskCreatorProps) {
  const [query, setQuery] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Guard against double submission: a second click while the first request
    // is in flight would create a duplicate task, each with its own plan.
    if (!query.trim() || loading) return;
    await onSubmit(query.trim());
  };

  return (
    <div className="w-full max-w-3xl mx-auto py-12 px-4">
      <div className="text-center mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-950/80 border border-indigo-800/60 text-indigo-400 text-xs font-medium mb-4">
          <span className="h-2 w-2 rounded-full bg-indigo-400 animate-pulse" />
          Human-in-the-Loop Architecture
        </div>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-zinc-100 mb-3">
          What would you like to investigate?
        </h1>
        <p className="text-sm text-zinc-400 max-w-xl mx-auto">
          The agent will formulate a draft plan, clarify ambiguities, and wait for your review and approval before running web searches.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="mb-8">
        <div className="relative rounded-2xl bg-zinc-900 border border-zinc-800 p-2 shadow-2xl focus-within:border-indigo-500/80 focus-within:ring-1 focus-within:ring-indigo-500/50 transition-all">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="E.g., Compare state-of-the-art solid state battery chemistry and cell density across leading manufacturers..."
            rows={3}
            className="w-full bg-transparent p-3 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-hidden resize-none"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
          />
          <div className="flex items-center justify-between pt-2 px-3 border-t border-zinc-800/80">
            <span className="text-[11px] text-zinc-500">
              Press <kbd className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono text-[10px]">⌘+Enter</kbd> to submit
            </span>
            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600 text-white text-xs font-semibold rounded-xl shadow-md transition-all cursor-pointer"
            >
              {loading ? (
                <>
                  <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Drafting Plan...
                </>
              ) : (
                <>
                  Draft Research Plan
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </>
              )}
            </button>
          </div>
        </div>
      </form>

      <div>
        <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
          Example Research Inquiries
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          {SAMPLE_PROMPTS.map((prompt, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => setQuery(prompt)}
              className="p-3 text-left bg-zinc-900/50 hover:bg-zinc-900 border border-zinc-800/80 hover:border-zinc-700 rounded-xl text-xs text-zinc-300 hover:text-zinc-100 transition-all cursor-pointer group"
            >
              <div className="flex items-start gap-2">
                <span className="text-indigo-400 font-mono text-[11px] group-hover:translate-x-0.5 transition-transform">→</span>
                <span>{prompt}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
