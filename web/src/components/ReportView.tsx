/**
 * Research Report Presentation Component: renders synthesized findings, evidence ledger, and citation audit.
 *
 * Information Hierarchy:
 *   1. Status Header & Share Bar: Public link toggle and copy button.
 *   2. Metrics Telemetry Bar: Actual dollar cost vs pre-flight estimate, token count, searches, and provider.
 *   3. Citation Audit Banner: Rendered prominently *above* the prose so readers can inspect hallucination
 *      verification before trusting sentences in the report.
 *   4. Markdown Body: Rendered with glowing inline citation badges (`[1]`, `[2]`).
 *   5. Retrieved Evidence Ledger: Full list of retrieved pages with snippets and veto indicators.
 */
"use client";

import React, { useState } from "react";
import { formatUsd, TaskDetail } from "@/lib/api";
import { CitationAudit } from "@/components/CitationAudit";

/** Props for ReportView component */
interface ReportViewProps {
  /** Completed research task detail */
  task: TaskDetail;
  /** Optional callback to toggle public sharing URL */
  onToggleShare?: () => Promise<void>;
  /** Callback to initiate a new research inquiry */
  onNewTask: () => void;
}

/**
 * Renders the full synthesized research report with source audit and telemetry metrics.
 */
export function ReportView({ task, onToggleShare, onNewTask }: ReportViewProps) {
  const [copied, setCopied] = useState(false);
  const [sharing, setSharing] = useState(false);

  // Construct absolute public share URL
  const shareUrl =
    typeof window !== "undefined" && task.share_id
      ? `${window.location.origin}/share/${task.share_id}`
      : "";

  /**
   * Copy public share URL to clipboard.
   */
  const handleCopyLink = () => {
    if (!shareUrl) return;
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  /**
   * Toggle public share status via parent callback.
   */
  const handleShareClick = async () => {
    if (!onToggleShare) return;
    setSharing(true);
    try {
      await onToggleShare();
    } finally {
      setSharing(false);
    }
  };

  /**
   * Lightweight client-side Markdown parser for reports.
   */
  const renderMarkdown = (content: string) => {
    if (!content) return null;

    const lines = content.split("\n");
    const elements: React.ReactNode[] = [];

    lines.forEach((line, index) => {
      // H1 Header
      if (line.startsWith("# ")) {
        elements.push(
          <h1 key={index} className="text-2xl sm:text-3xl font-bold text-zinc-100 mt-6 mb-3">
            {line.replace("# ", "")}
          </h1>
        );
      }
      // H2 Section Header
      else if (line.startsWith("## ")) {
        elements.push(
          <h2 key={index} className="text-lg sm:text-xl font-semibold text-zinc-200 mt-6 mb-2 border-b border-zinc-800 pb-1.5">
            {line.replace("## ", "")}
          </h2>
        );
      }
      // H3 Subsection Header
      else if (line.startsWith("### ")) {
        elements.push(
          <h3 key={index} className="text-base font-semibold text-zinc-300 mt-4 mb-1.5">
            {line.replace("### ", "")}
          </h3>
        );
      }
      // Blockquote
      else if (line.startsWith("> ")) {
        elements.push(
          <blockquote key={index} className="border-l-2 border-indigo-500 pl-3.5 italic text-zinc-400 my-3 text-xs sm:text-sm">
            {line.replace("> ", "")}
          </blockquote>
        );
      }
      // Unordered list items
      else if (line.startsWith("- ") || line.startsWith("* ")) {
        const text = line.replace(/^[-*]\s+/, "");
        elements.push(
          <li key={index} className="ml-4 list-disc text-zinc-300 my-1 text-xs sm:text-sm leading-relaxed">
            {renderFormattedInline(text)}
          </li>
        );
      }
      // Numbered list items
      else if (/^\d+\.\s+/.test(line)) {
        const text = line.replace(/^\d+\.\s+/, "");
        elements.push(
          <li key={index} className="ml-4 list-decimal text-zinc-300 my-1 text-xs sm:text-sm leading-relaxed">
            {renderFormattedInline(text)}
          </li>
        );
      }
      // Empty spacer line
      else if (!line.trim()) {
        elements.push(<div key={index} className="h-2" />);
      }
      // Regular paragraph
      else {
        elements.push(
          <p key={index} className="text-zinc-300 my-2 text-xs sm:text-sm leading-relaxed">
            {renderFormattedInline(line)}
          </p>
        );
      }
    });

    return elements;
  };

  /**
   * Format inline elements: bold, italic, inline code, and citation badges `[N]`.
   */
  const renderFormattedInline = (text: string) => {
    // Replace citation numbers like [1], [2] with styled badge spans
    const parts = text.split(/(\[\d+\]|\*\*.*?\*\*|\*.*?\*|`.*?`)/g);

    return parts.map((part, i) => {
      if (/^\[\d+\]$/.test(part)) {
        return (
          <span
            key={i}
            className="inline-flex items-center px-1.5 py-0.2 mx-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800/60 font-mono text-[10px] font-bold"
          >
            {part}
          </span>
        );
      }
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i} className="font-semibold text-zinc-100">{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("*") && part.endsWith("*")) {
        return <em key={i} className="italic text-zinc-300">{part.slice(1, -1)}</em>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return <code key={i} className="px-1.5 py-0.5 rounded bg-zinc-800 text-indigo-300 font-mono text-[11px]">{part.slice(1, -1)}</code>;
      }
      return part;
    });
  };

  return (
    <div className="w-full max-w-4xl mx-auto py-8 px-4">
      {/* Top Header */}
      <div className="mb-6 p-5 rounded-2xl bg-zinc-900 border border-zinc-800">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-zinc-800">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2 py-0.5 rounded-full bg-emerald-950/80 border border-emerald-800/60 text-emerald-400 text-[10px] font-bold uppercase tracking-wider">
                ✓ Research Complete
              </span>
              {task.is_public && (
                <span className="px-2 py-0.5 rounded-full bg-indigo-950/80 border border-indigo-800/60 text-indigo-400 text-[10px] font-bold uppercase tracking-wider">
                  Public Report
                </span>
              )}
            </div>
            <h1 className="text-xl font-bold text-zinc-100">{task.query}</h1>
          </div>

          <div className="flex items-center gap-2">
            {onToggleShare && (
              <button
                onClick={handleShareClick}
                disabled={sharing}
                className="px-3.5 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-semibold rounded-xl border border-zinc-700 transition-colors cursor-pointer"
              >
                {sharing
                  ? "Updating..."
                  : task.is_public
                  ? "Make Private"
                  : "Share Publicly"}
              </button>
            )}
            <button
              onClick={onNewTask}
              className="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-xl shadow-sm transition-colors cursor-pointer"
            >
              + New Query
            </button>
          </div>
        </div>

        {/* Metrics Telemetry Bar */}
        <div className="mt-3.5 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <div className="p-2.5 rounded-xl bg-zinc-950/60 border border-zinc-800/80">
            <span className="text-[10px] uppercase font-bold text-zinc-500 block">Searches</span>
            <span className="text-zinc-200 font-mono font-semibold">{task.searches_used} queries</span>
          </div>
          <div className="p-2.5 rounded-xl bg-zinc-950/60 border border-zinc-800/80">
            <span className="text-[10px] uppercase font-bold text-zinc-500 block">Cost</span>
            <span className="text-zinc-200 font-mono font-semibold">
              {formatUsd(task.actual_cost_usd)}
              {task.estimated_cost_usd != null && (
                <span className="text-zinc-500 font-normal">
                  {" "}
                  (est. {formatUsd(task.estimated_cost_usd)})
                </span>
              )}
            </span>
          </div>
          <div className="p-2.5 rounded-xl bg-zinc-950/60 border border-zinc-800/80">
            <span className="text-[10px] uppercase font-bold text-zinc-500 block">Provider / Model</span>
            <span className="text-zinc-200 font-mono font-semibold truncate block">
              {task.provider || "anthropic"} ({task.model || "opus-5"})
            </span>
          </div>
          <div className="p-2.5 rounded-xl bg-zinc-950/60 border border-zinc-800/80">
            <span className="text-[10px] uppercase font-bold text-zinc-500 block">Sources Read</span>
            <span className="text-zinc-200 font-mono font-semibold">{task.sources?.length || 0} pages</span>
          </div>
        </div>

        {/* Public Link Share Bar */}
        {task.is_public && task.share_id && (
          <div className="mt-4 p-3 rounded-xl bg-indigo-950/30 border border-indigo-800/40 flex items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2 overflow-hidden">
              <span className="text-indigo-400 font-bold shrink-0">🔗 Public Link:</span>
              <span className="text-zinc-300 font-mono truncate text-[11px]">{shareUrl}</span>
            </div>
            <button
              onClick={handleCopyLink}
              className="shrink-0 px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-[11px] font-medium transition-colors cursor-pointer"
            >
              {copied ? "Copied!" : "Copy Link"}
            </button>
          </div>
        )}
      </div>

      {/* Did the report cite anything the agent never actually retrieved? */}
      {task.citation_report && <CitationAudit report={task.citation_report} />}

      {/* Main Report Body */}
      <div className="p-6 sm:p-8 rounded-2xl bg-zinc-900 border border-zinc-800 shadow-xl mb-6 prose-invert">
        {task.report_markdown ? (
          renderMarkdown(task.report_markdown)
        ) : (
          <div className="text-zinc-400 text-sm">No report markdown available.</div>
        )}
      </div>

      {/* Sources Ledger */}
      {task.sources && task.sources.length > 0 && (
        <div className="p-6 rounded-2xl bg-zinc-900 border border-zinc-800">
          <h3 className="text-sm font-bold uppercase tracking-wider text-zinc-300 mb-4">
            Retrieved Sources & Evidence ({task.sources.filter((s) => !s.excluded).length})
          </h3>
          <div className="space-y-3">
            {task.sources.map((source, idx) => (
              <div
                key={source.id}
                className={`p-3.5 rounded-xl border ${
                  source.excluded
                    ? "bg-red-950/20 border-red-900/40 opacity-50 line-through"
                    : "bg-zinc-950/80 border-zinc-800/80 hover:border-zinc-700"
                } text-xs transition-colors`}
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-indigo-400 font-bold">[{idx + 1}]</span>
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-zinc-100 hover:text-indigo-400 transition-colors line-clamp-1"
                    >
                      {source.title || source.url}
                    </a>
                  </div>
                  {source.excluded && (
                    <span className="text-[10px] text-red-400 font-medium">Vetoed by human</span>
                  )}
                </div>
                <p className="text-zinc-400 text-[11px] leading-relaxed line-clamp-2">
                  {source.snippet}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

