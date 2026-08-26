/**
 * Human-in-the-Loop Frontend API Client.
 *
 * Security Architecture:
 *   - Every client-side call routes through this application's own origin (`/api/proxy/*` or `/api/auth/*`).
 *   - The session JWT token is stored inside an `httpOnly` cookie that only server-side
 *     Next.js route handlers can access.
 *   - JavaScript running in the browser never interacts with the raw JWT, ensuring complete immunity
 *     from client-side token exfiltration attacks.
 */

/** Valid states in the research task lifecycle */
export type TaskStatus =
  | "queued"
  | "planning"
  | "awaiting_approval"
  | "researching"
  | "complete"
  | "failed"
  | "cancelled";

/** Terminal lifecycle states where background task processing has concluded */
export const TERMINAL_STATUSES: TaskStatus[] = ["complete", "failed", "cancelled"];

/** Authenticated user profile structure */
export interface User {
  id: string;
  email: string;
  created_at: string;
}

/** Lightweight task representation used in the sidebar list view */
export interface TaskSummary {
  id: string;
  query: string;
  status: TaskStatus;
  created_at: string;
  completed_at?: string | null;
}

/** Monotonic progress event displayed on the live research timeline */
export interface TaskEvent {
  id: string;
  seq: number;
  kind: "status" | "search" | "thought" | "error" | "warning" | string;
  message: string;
  data?: Record<string, unknown> | null;
  created_at: string;
}

/** Retrieved web source item recorded in the source ledger */
export interface Source {
  id: string;
  url: string;
  title: string;
  snippet: string;
  excluded: boolean;
}

/** Output of the citation audit - compares cited URLs in Markdown against genuinely retrieved sources */
export interface CitationReport {
  cited_count: number;
  verified_count: number;
  unverified_count: number;
  unused_count: number;
  verified_ratio: number;
  is_clean: boolean;
  verified: string[];
  unverified: string[];
  unused: string[];
}

/** Pre-flight pricing estimate computed for candidate research plans */
export interface CostEstimate {
  model: string;
  expected_usd: number;
  low_usd: number;
  high_usd: number;
  expected_searches: number;
  expected_turns: number;
  priced: boolean;
}

/** Incremental event page payload for low-bandwidth cursor polling */
export interface EventsPage {
  task_id: string;
  status: TaskStatus;
  cursor: number;
  events: TaskEvent[];
  searches_used: number;
  actual_cost_usd: number;
  done: boolean;
}

/** Comprehensive task view including full plan, token usage, events, and citations */
export interface TaskDetail extends TaskSummary {
  clarifying_questions?: string[] | null;
  clarification_answers?: Record<string, string> | null;
  plan?: string[] | null;
  plan_edited_by_user: boolean;
  report_markdown?: string | null;
  error?: string | null;
  share_id?: string | null;
  is_public: boolean;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  searches_used: number;
  estimated_cost_usd?: number | null;
  actual_cost_usd: number;
  citation_report?: CitationReport | null;
  provider?: string | null;
  model?: string | null;
  events: TaskEvent[];
  sources: Source[];
}

/** Publicly viewable shared report structure */
export interface PublicReport {
  query: string;
  report_markdown: string;
  created_at: string;
  sources: Source[];
}

/** Custom error wrapper holding HTTP status codes from API failures */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Parse structured JSON error payloads or fall back to standard HTTP status strings.
 */
async function parseError(res: Response, fallback: string): Promise<never> {
  let detail = fallback;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // Non-JSON error body; keep the fallback message.
  }
  throw new ApiError(detail, res.status);
}

/**
 * Calls backend endpoints through the authenticated server proxy (`/api/proxy/*`).
 */
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers ?? {});
  if (options.body) headers.set("Content-Type", "application/json");

  const res = await fetch(`/api/proxy${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (!res.ok) await parseError(res, `Request failed (${res.status})`);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/**
 * Calls local Next.js route handlers for authentication and cookie setting.
 */
async function local<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) await parseError(res, `Request failed (${res.status})`);
  return (await res.json()) as T;
}

/**
 * Strongly-typed API client module.
 */
export const api = {
  auth: {
    /** Register a new user and set the session cookie */
    async register(email: string, password: string): Promise<void> {
      await local("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
    },
    /** Log into an existing account and set the session cookie */
    async login(email: string, password: string): Promise<void> {
      await local("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
    },
    /** Invalidate session and clear the session cookie */
    async logout(): Promise<void> {
      await local("/api/auth/logout", { method: "POST" });
    },
    /** Fetch current user profile */
    async me(): Promise<User> {
      return request<User>("/api/auth/me");
    },
    /** Permanently delete account and all cascading data */
    async deleteAccount(): Promise<void> {
      await request<void>("/api/auth/me", { method: "DELETE" });
    },
  },
  tasks: {
    /** Create a new research task */
    async create(query: string): Promise<TaskDetail> {
      return request<TaskDetail>("/api/tasks", {
        method: "POST",
        body: JSON.stringify({ query }),
      });
    },
    /** List all tasks belonging to the authenticated user */
    async list(): Promise<TaskSummary[]> {
      return request<TaskSummary[]>("/api/tasks");
    },
    /** Fetch full task detail including events and sources */
    async get(taskId: string): Promise<TaskDetail> {
      return request<TaskDetail>(`/api/tasks/${taskId}`);
    },
    /** Poll incremental progress events strictly newer than sequence cursor `after` */
    async events(taskId: string, after: number): Promise<EventsPage> {
      return request<EventsPage>(`/api/tasks/${taskId}/events?after=${after}`);
    },
    /** Fetch pre-flight pricing estimate for the current saved plan */
    async estimate(taskId: string): Promise<CostEstimate> {
      return request<CostEstimate>(`/api/tasks/${taskId}/estimate`);
    },
    /** Price an edited candidate plan before submitting approval */
    async estimateFor(taskId: string, plan: string[]): Promise<CostEstimate> {
      return request<CostEstimate>(`/api/tasks/${taskId}/estimate`, {
        method: "POST",
        body: JSON.stringify({ plan }),
      });
    },
    /** Submit human approval gate payload and dispatch autonomous research */
    async approve(
      taskId: string,
      plan: string[],
      answers: Record<string, string>,
    ): Promise<TaskDetail> {
      return request<TaskDetail>(`/api/tasks/${taskId}/approve`, {
        method: "POST",
        body: JSON.stringify({ plan, answers }),
      });
    },
    /** Cancel a running task between agent turns */
    async cancel(taskId: string): Promise<TaskDetail> {
      return request<TaskDetail>(`/api/tasks/${taskId}/cancel`, { method: "POST" });
    },
    /** Toggle exclusion veto on a retrieved source */
    async toggleSource(taskId: string, sourceId: string): Promise<Source> {
      return request<Source>(`/api/tasks/${taskId}/sources/${sourceId}/toggle`, {
        method: "POST",
      });
    },
    /** Toggle public sharing link visibility */
    async toggleShare(taskId: string): Promise<TaskDetail> {
      return request<TaskDetail>(`/api/tasks/${taskId}/share`, { method: "POST" });
    },
    /** Construct PDF download URL */
    pdfUrl(taskId: string): string {
      return `/api/proxy/api/tasks/${taskId}/pdf`;
    },
  },
  public: {
    /** Fetch unauthenticated shared research report */
    async getReport(shareId: string): Promise<PublicReport> {
      const res = await fetch(`/api/share/${shareId}`, { cache: "no-store" });
      if (!res.ok) await parseError(res, "Report not found");
      return (await res.json()) as PublicReport;
    },
  },
};

/**
 * Pulls a human-readable message off an unknown thrown exception.
 *
 * @param err - Unknown error object.
 * @param fallback - Default fallback text.
 * @returns Human-readable error description.
 */
export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

/**
 * Formats a dollar amount into a readable USD currency string.
 * Handles sub-cent amounts gracefully (e.g. `<$0.01`).
 *
 * @param amount - Dollar amount number or null/undefined.
 * @returns Formatted currency string.
 */
export function formatUsd(amount: number | null | undefined): string {
  if (amount == null) return "—";
  if (amount === 0) return "$0.00";
  if (amount < 0.01) return `<$0.01`;
  return `$${amount.toFixed(2)}`;
}

