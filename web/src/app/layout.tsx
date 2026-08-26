/** Root document shell and application-wide metadata. */
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Human in the Loop — Agentic Research Assistant",
  description: "A human-in-the-loop deep research agent with approval gates, live execution telemetry, source vetoes, and spend caps.",
};

/**
 * Root layout. Dark theme is applied on <html> rather than toggled after mount,
 * so the first paint is already dark and there is no flash of a light page.
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
