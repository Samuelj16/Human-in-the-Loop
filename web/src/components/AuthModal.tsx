/**
 * Login and registration.
 *
 * Credentials go to this app's own route handlers, not to the API directly.
 * Those handlers exchange them for a token and store it in an httpOnly cookie,
 * so the token never touches client JavaScript and an XSS bug cannot steal a
 * session. See src/lib/session.ts.
 */
"use client";

import React, { useState } from "react";
import { api, User, errorMessage } from "@/lib/api";

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (user: User) => void;
}

export function AuthModal({ isOpen, onClose, onSuccess }: AuthModalProps) {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (isRegister) {
        await api.auth.register(email, password);
      } else {
        await api.auth.login(email, password);
      }
      const user = await api.auth.me();
      onSuccess(user);
      onClose();
    } catch (err: unknown) {
      setError(errorMessage(err, "Authentication failed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs">
      <div
        className="w-full max-w-md bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-2xl relative"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer"
        >
          ✕
        </button>

        <div className="mb-6 text-center">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-400 font-bold mb-3 border border-indigo-500/20">
            H
          </div>
          <h2 className="text-xl font-bold text-zinc-100">
            {isRegister ? "Create an account" : "Welcome back"}
          </h2>
          <p className="text-xs text-zinc-400 mt-1">
            {isRegister
              ? "Sign up to create and review research tasks."
              : "Sign in to access your research tasks and reports."}
          </p>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-950/50 border border-red-800/60 text-red-300 text-xs">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-zinc-300 mb-1">
              Email Address
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="researcher@example.com"
              className="w-full px-3.5 py-2.5 bg-zinc-950 border border-zinc-800 rounded-lg text-sm text-zinc-100 placeholder-zinc-500 focus:outline-hidden focus:border-indigo-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-zinc-300 mb-1">
              Password
            </label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Minimum 8 characters"
              className="w-full px-3.5 py-2.5 bg-zinc-950 border border-zinc-800 rounded-lg text-sm text-zinc-100 placeholder-zinc-500 focus:outline-hidden focus:border-indigo-500 transition-colors"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold rounded-lg shadow-sm transition-colors cursor-pointer"
          >
            {loading ? "Processing..." : isRegister ? "Create Account" : "Sign In"}
          </button>
        </form>

        <div className="mt-5 text-center text-xs text-zinc-400">
          {isRegister ? "Already have an account?" : "Don't have an account yet?"}{" "}
          <button
            onClick={() => {
              setIsRegister(!isRegister);
              setError(null);
            }}
            className="text-indigo-400 hover:text-indigo-300 font-medium underline underline-offset-2 cursor-pointer"
          >
            {isRegister ? "Sign in" : "Register"}
          </button>
        </div>
      </div>
    </div>
  );
}
