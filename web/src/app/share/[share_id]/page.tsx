/**
 * Public Report Share Page (`/share/[share_id]`).
 *
 * Architecture & Access Control:
 *   - Accessible publicly without requiring login or session cookies.
 *   - Fetches data through Next.js server route `/api/share/[shareId]`, calling FastAPI `/api/public/reports/{share_id}`.
 *   - Non-existent or unshared reports return 404 to avoid leaking valid share IDs.
 *   - Renders formatted Markdown content, publication date, and non-excluded source references.
 */
"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, errorMessage, PublicReport } from "@/lib/api";

/**
 * Public report viewing page component.
 */
export default function PublicReportPage() {
  const params = useParams();
  const shareId = params.share_id as string;

  const [report, setReport] = useState<PublicReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!shareId) return;
    let cancelled = false;

    // `loading` already starts true, so there is no synchronous setState here -
    // setting it in the effect body would cause a cascading render.
    api.public
      .getReport(shareId)
      .then((rep) => {
        if (!cancelled) setReport(rep);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorMessage(err, "Failed to load public report"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [shareId]);

  /**
   * Parse Markdown report body into formatted React elements.
   */
  const renderMarkdown = (content: string) => {
    if (!content) return null;

    const lines = content.split("\n");
    const elements: React.ReactNode[] = [];

    lines.forEach((line, index) => {
      if (line.startsWith("# ")) {
        elements.push(
          <h1 key={index} className="text-2xl sm:text-3xl font-bold text-zinc-100 mt-6 mb-3">
            {line.replace("# ", "")}
          </h1>
        );
      } else if (line.startsWith("## ")) {
        elements.push(
          <h2 key={index} className="text-lg sm:text-xl font-semibold text-zinc-200 mt-6 mb-2 border-b border-zinc-800 pb-1.5">
            {line.replace("## ", "")}
          </h2>
        );
      } else if (line.startsWith("### ")) {
        elements.push(
          <h3 key={index} className="text-base font-semibold text-zinc-300 mt-4 mb-1.5">
            {line.replace("### ", "")}
          </h3>
        );
      } else if (line.startsWith("> ")) {
        elements.push(
          <blockquote key={index} className="border-l-2 border-indigo-500 pl-3.5 italic text-zinc-400 my-3 text-xs sm:text-sm">
            {line.replace("> ", "")}
          </blockquote>
        );
      } else if (line.startsWith("- ") || line.startsWith("* ")) {
        elements.push(
          <li key={index} className="ml-4 list-disc text-zinc-300 my-1 text-xs sm:text-sm leading-relaxed">
            {line.replace(/^[-*]\s+/, "")}
          </li>
        );
      } else if (/^\d+\.\s+/.test(line)) {
        elements.push(
          <li key={index} className="ml-4 list-decimal text-zinc-300 my-1 text-xs sm:text-sm leading-relaxed">
            {line.replace(/^\d+\.\s+/, "")}
          </li>
        );
      } else if (!line.trim()) {
        elements.push(<div key={index} className="h-2" />);
      } else {
        elements.push(
          <p key={index} className="text-zinc-300 my-2 text-xs sm:text-sm leading-relaxed">
            {line}
          </p>
        );
      }
    });

    return elements;
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Public view header */}
      <header className="border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md px-6 py-3.5 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-3 group cursor-pointer">
          <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white shadow-lg text-xs">
            H
          </div>
          <span className="font-semibold text-sm tracking-tight text-zinc-100 group-hover:text-indigo-400 transition-colors">
            Human in the Loop
          </span>
        </Link>
        <Link
          href="/"
          className="px-3 py-1.5 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg transition-colors cursor-pointer"
        >
          Conduct Your Own Research
        </Link>
      </header>

      {/* Main content viewport */}
      <main className="flex-1 max-w-4xl w-full mx-auto py-10 px-4">
        {loading ? (
          <div className="p-12 text-center text-zinc-500 text-sm">
            <svg className="animate-spin h-6 w-6 mx-auto mb-3 text-indigo-400" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            Loading research report...
          </div>
        ) : error || !report ? (
          <div className="p-8 rounded-2xl bg-zinc-900 border border-zinc-800 text-center">
            <div className="text-3xl mb-2">🔒</div>
            <h2 className="text-lg font-bold text-zinc-100 mb-1">
              Report Not Found or Private
            </h2>
            <p className="text-xs text-zinc-400 mb-4">
              {error || "This report does not exist or has been made private by its author."}
            </p>
            <Link
              href="/"
              className="inline-block px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-xl transition-colors"
            >
              Go to Home
            </Link>
          </div>
        ) : (
          <div>
            <div className="mb-6 p-6 rounded-2xl bg-zinc-900 border border-zinc-800">
              <div className="flex items-center gap-2 mb-2">
                <span className="px-2 py-0.5 rounded-full bg-indigo-950 border border-indigo-800 text-indigo-400 text-[10px] font-bold uppercase tracking-wider">
                  Shared Research Report
                </span>
                <span className="text-[11px] font-mono text-zinc-500">
                  {new Date(report.created_at).toLocaleDateString([], {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })}
                </span>
              </div>
              <h1 className="text-2xl font-bold text-zinc-100">{report.query}</h1>
            </div>

            <div className="p-8 rounded-2xl bg-zinc-900 border border-zinc-800 shadow-xl mb-6 prose-invert">
              {renderMarkdown(report.report_markdown)}
            </div>

            {report.sources && report.sources.length > 0 && (
              <div className="p-6 rounded-2xl bg-zinc-900 border border-zinc-800">
                <h3 className="text-sm font-bold uppercase tracking-wider text-zinc-300 mb-4">
                  Cited References ({report.sources.length})
                </h3>
                <div className="space-y-3">
                  {report.sources.map((source, idx) => (
                    <div
                      key={source.id}
                      className="p-3.5 rounded-xl bg-zinc-950 border border-zinc-800/80 text-xs"
                    >
                      <div className="flex items-center gap-2 mb-1">
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
                      <p className="text-zinc-400 text-[11px] leading-relaxed line-clamp-2">
                        {source.snippet}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

