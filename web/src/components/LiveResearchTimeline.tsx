/** Polling timeline for task progress, searches, and source-veto controls. */
"use client";

import React, { useEffect, useRef } from "react";
import { TaskDetail } from "@/lib/api";

interface LiveResearchTimelineProps {
  task: TaskDetail;
  onCancel: () => Promise<void>;
  onToggleSource: (sourceId: string) => Promise<void>;
  cancelling: boolean;
}

export function LiveResearchTimeline({
  task,
  onCancel,
  onToggleSource,
  cancelling,
}: LiveResearchTimelineProps) {
  const eventsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [task.events?.length]);

  const renderEventIcon = (kind: string) => {
    switch (kind) {
      case "search":
        return <span className="text-cyan-400">🔍</span>;
      case "thought":
        return <span className="text-purple-400">💭</span>;
      case "error":
        return <span className="text-red-400">⚠️</span>;
      default:
        return <span className="text-emerald-400">⚡</span>;
    }
  };

  return (
    <div className="w-full max-w-5xl mx-auto py-8 px-4">
      {/* Top Status Header */}
      <div className="mb-6 p-5 rounded-2xl bg-zinc-900 border border-zinc-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5 mb-1.5">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-cyan-500"></span>
            </span>
            <span className="text-xs font-bold uppercase tracking-wider text-cyan-400">
              {task.status === "planning"
                ? "Formulating Research Plan"
                : "Live Web Investigation in Progress"}
            </span>
          </div>
          <h2 className="text-base font-semibold text-zinc-100 line-clamp-1">
            {task.query}
          </h2>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right text-xs">
            <div className="text-zinc-400 font-mono">
              Searches: <strong className="text-zinc-200">{task.searches_used}</strong>
            </div>
            <div className="text-zinc-500 text-[11px] font-mono">
              Tokens: {task.input_tokens + task.output_tokens}
            </div>
          </div>
          <button
            onClick={onCancel}
            disabled={cancelling}
            className="px-3.5 py-1.5 text-xs font-medium text-red-400 hover:text-red-300 bg-red-950/40 hover:bg-red-950/80 border border-red-800/60 rounded-xl transition-colors cursor-pointer"
          >
            {cancelling ? "Cancelling..." : "Stop Agent"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Events Timeline (2 cols) */}
        <div className="lg:col-span-2 p-5 rounded-2xl bg-zinc-900 border border-zinc-800 flex flex-col h-[520px]">
          <div className="flex items-center justify-between pb-3 border-b border-zinc-800 mb-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
              Agent Telemetry Feed
            </h3>
            <span className="text-[11px] font-mono text-zinc-500">
              {task.events?.length || 0} events
            </span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-3 pr-1 text-xs">
            {task.events && task.events.length > 0 ? (
              task.events.map((evt) => (
                <div
                  key={evt.id}
                  className={`p-3 rounded-xl border ${
                    evt.kind === "error"
                      ? "bg-red-950/30 border-red-800/50 text-red-300"
                      : evt.kind === "search"
                      ? "bg-cyan-950/20 border-cyan-800/40 text-cyan-200"
                      : evt.kind === "thought"
                      ? "bg-purple-950/20 border-purple-800/40 text-purple-200"
                      : "bg-zinc-950/80 border-zinc-800/80 text-zinc-300"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1.5 font-semibold text-[11px] uppercase tracking-wide">
                      {renderEventIcon(evt.kind)}
                      <span>{evt.kind}</span>
                    </div>
                    <span className="text-[10px] font-mono text-zinc-500">
                      {new Date(evt.created_at).toLocaleTimeString()}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap leading-relaxed">
                    {evt.message}
                  </p>
                </div>
              ))
            ) : (
              <div className="h-full flex items-center justify-center text-zinc-500 text-xs">
                Awaiting telemetry updates...
              </div>
            )}
            <div ref={eventsEndRef} />
          </div>
        </div>

        {/* Real-time Sources Ledger with Human Veto Toggle */}
        <div className="p-5 rounded-2xl bg-zinc-900 border border-zinc-800 flex flex-col h-[520px]">
          <div className="flex items-center justify-between pb-3 border-b border-zinc-800 mb-3">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
                Source Ledger
              </h3>
              <p className="text-[10px] text-zinc-500">Veto unwanted sources</p>
            </div>
            <span className="text-[11px] font-mono text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800/50">
              {task.sources?.length || 0}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2.5 pr-1 text-xs">
            {task.sources && task.sources.length > 0 ? (
              task.sources.map((src) => (
                <div
                  key={src.id}
                  className={`p-3 rounded-xl border transition-all ${
                    src.excluded
                      ? "bg-red-950/20 border-red-900/40 opacity-60 line-through"
                      : "bg-zinc-950/80 border-zinc-800/80 hover:border-zinc-700"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <a
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-indigo-400 hover:underline line-clamp-1 text-[11px]"
                    >
                      {src.title || src.url}
                    </a>
                    <button
                      onClick={() => onToggleSource(src.id)}
                      className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-medium transition-colors cursor-pointer ${
                        src.excluded
                          ? "bg-emerald-950 text-emerald-400 border border-emerald-800/60 hover:bg-emerald-900"
                          : "bg-red-950 text-red-400 border border-red-800/60 hover:bg-red-900"
                      }`}
                      title={src.excluded ? "Restore source" : "Exclude / Veto source"}
                    >
                      {src.excluded ? "Restore" : "Veto"}
                    </button>
                  </div>
                  <p className="text-[11px] text-zinc-400 line-clamp-2 leading-relaxed">
                    {src.snippet}
                  </p>
                </div>
              ))
            ) : (
              <div className="h-full flex items-center justify-center text-zinc-500 text-xs text-center px-4">
                Retrieved URLs will appear here as the agent reads the web.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
