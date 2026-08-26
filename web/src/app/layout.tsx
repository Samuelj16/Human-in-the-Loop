/**
 * Root Document Shell & Application Layout (`/app/layout.tsx`).
 *
 * Design & Styling Rationale:
 *   - Dark theme class (`dark`) is hard-coded onto the `<html>` root element.
 *   - Prevents Flash of Unstyled Content (FOUC) or bright white screen flicker on initial server render.
 *   - Configures global typography, dark zinc background palette, and text selection accents.
 */
import type { Metadata } from "next";
import "./globals.css";

/** Global metadata for page headers, SEO, and social previews */
export const metadata: Metadata = {
  title: "Human in the Loop — Agentic Research Assistant",
  description:
    "A human-in-the-loop deep research agent with approval gates, live execution telemetry, source vetoes, and spend caps.",
};

/**
 * Root Layout Component: wraps all pages within the application.
 *
 * @param children - React page children nodes.
 * @returns Root HTML shell.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased dark">
      <body className="min-h-full flex flex-col bg-zinc-950 text-zinc-100 font-sans selection:bg-indigo-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}

