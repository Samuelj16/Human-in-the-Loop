/**
 * Top navigation bar component: branding, new task trigger, and user session management.
 *
 * Design Notes:
 *   - The authenticated user's state is fetched from `/api/auth/me` by the parent component.
 *   - Clicking the logo or "New Research" triggers `onNewTask`, switching the main viewport
 *     to the research creation prompt.
 *   - Unauthenticated state provides an entry point to open the `AuthModal`.
 */
"use client";

import React from "react";
import { User } from "@/lib/api";

/** Props for Navbar component */
interface NavbarProps {
  /** Authenticated user profile or null if unauthenticated */
  user: User | null;
  /** Callback to launch the authentication modal */
  onOpenAuth: () => void;
  /** Callback to clear user session and log out */
  onLogout: () => void;
  /** Callback to initiate a fresh research inquiry */
  onNewTask: () => void;
}

/**
 * Renders the global application navigation header.
 */
export function Navbar({ user, onOpenAuth, onLogout, onNewTask }: NavbarProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md px-6 py-3.5 flex items-center justify-between">
      {/* Brand logo & tagline */}
      <div className="flex items-center gap-4">
        <button
          onClick={onNewTask}
          className="flex items-center gap-3 text-left group transition-transform active:scale-98 cursor-pointer"
        >
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/20">
            H
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm tracking-tight text-zinc-100 group-hover:text-indigo-400 transition-colors">
                Human in the Loop
              </span>
              <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-indigo-950/80 text-indigo-400 border border-indigo-800/50">
                Research Agent
              </span>
            </div>
            <p className="text-xs text-zinc-400">Autonomous research with human approval gates</p>
          </div>
        </button>
      </div>

      {/* Action buttons & session status */}
      <div className="flex items-center gap-3">
        <button
          onClick={onNewTask}
          className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-zinc-200 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 rounded-lg transition-colors cursor-pointer"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Research
        </button>

        {user ? (
          <div className="flex items-center gap-3 pl-3 border-l border-zinc-800">
            <div className="flex flex-col text-right">
              <span className="text-xs font-medium text-zinc-200">{user.email}</span>
              <span className="text-[10px] text-emerald-400">● Active</span>
            </div>
            <button
              onClick={onLogout}
              className="px-2.5 py-1 text-xs text-zinc-400 hover:text-zinc-200 bg-zinc-900/60 hover:bg-zinc-800/60 rounded border border-zinc-800 transition-colors cursor-pointer"
            >
              Sign out
            </button>
          </div>
        ) : (
          <button
            onClick={onOpenAuth}
            className="px-3.5 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg shadow-sm transition-colors cursor-pointer"
          >
            Sign In / Register
          </button>
        )}
      </div>
    </header>
  );
}

