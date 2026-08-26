/** Selectable summary list of the current user's research tasks. */
"use client";

import React from "react";
import { TaskStatus, TaskSummary } from "@/lib/api";

interface TaskListProps {
  tasks: TaskSummary[];
  activeTaskId: string | null;
  onSelectTask: (taskId: string) => void;
  onNewTask: () => void;
  loading: boolean;
}

export function TaskList({
  tasks,
  activeTaskId,
  onSelectTask,
  onNewTask,
  loading,
}: TaskListProps) {
  const getStatusBadge = (status: TaskStatus) => {
    switch (status) {
      case "awaiting_approval":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-800/60 animate-pulse">
            Needs Review
          </span>
        );
      case "planning":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-cyan-950 text-cyan-300 border border-cyan-800/60">
            Planning...
          </span>
        );
      case "researching":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-cyan-950 text-cyan-300 border border-cyan-800/60">
            Searching...
          </span>
        );
      case "complete":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-950 text-emerald-300 border border-emerald-800/60">
            Complete
          </span>
        );
      case "cancelled":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-zinc-800 text-zinc-400">
            Cancelled
          </span>
        );
      case "failed":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-950 text-red-300 border border-red-800/60">
            Failed
          </span>
        );
      default:
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-zinc-800 text-zinc-400">
            {status}
          </span>
        );
    }
  };

  return (
    <aside className="w-full sm:w-80 shrink-0 border-r border-zinc-800/80 bg-zinc-950/60 flex flex-col h-[calc(100vh-61px)]">
      <div className="p-4 border-b border-zinc-800/80 flex items-center justify-between">
        <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
          Research History
        </h2>
        <button
          onClick={onNewTask}
          className="px-2.5 py-1 text-xs font-medium text-indigo-300 hover:text-white bg-indigo-950 hover:bg-indigo-900 border border-indigo-800/60 rounded-lg transition-colors cursor-pointer"
        >
          + New Query
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {loading && tasks.length === 0 ? (
          <div className="p-4 text-center text-xs text-zinc-500">
            Loading tasks...
          </div>
        ) : tasks.length === 0 ? (
          <div className="p-6 text-center text-xs text-zinc-500 leading-relaxed">
            No research tasks yet. Enter a topic above to begin.
          </div>
        ) : (
          tasks.map((t) => {
            const isActive = t.id === activeTaskId;
            return (
              <button
                key={t.id}
                onClick={() => onSelectTask(t.id)}
                className={`w-full text-left p-3 rounded-xl border transition-all cursor-pointer ${
                  isActive
                    ? "bg-zinc-900 border-indigo-500/50 shadow-md shadow-indigo-950/20"
                    : "bg-zinc-900/30 hover:bg-zinc-900 border-zinc-800/60 hover:border-zinc-700"
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  {getStatusBadge(t.status)}
                  <span className="text-[10px] font-mono text-zinc-500">
                    {new Date(t.created_at).toLocaleDateString([], {
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                </div>
                <p
                  className={`text-xs line-clamp-2 leading-relaxed ${
                    isActive ? "font-semibold text-zinc-100" : "text-zinc-300"
                  }`}
                >
                  {t.query}
                </p>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
