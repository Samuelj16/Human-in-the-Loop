/**
 * Human in the Loop API client.
 *
 * Every call goes to this app's own origin. The session token lives in an
 * httpOnly cookie that only server-side route handlers can read, so there is
 * no token handling in this file at all - and nothing for an XSS bug to steal.
 */

export type TaskStatus =
  | "queued"
  | "planning"
  | "awaiting_approval"
  | "researching"
  | "complete"
  | "failed"
  | "cancelled";

export const TERMINAL_STATUSES: TaskStatus[] = ["complete", "failed", "cancelled"];

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface TaskSummary {
  id: string;
  query: string;
  status: TaskStatus;
  created_at: string;
  completed_at?: string | null;
}

export interface TaskEvent {
  id: string;
  seq: number;
  kind: "status" | "search" | "thought" | "error" | "warning" | string;
  message: string;
  data?: Record<string, unknown> | null;
  created_at: string;
}

export interface Source {
  id: string;
  url: string;
  title: string;
  snippet: string;
  excluded: boolean;
}

/** Output of the citation audit - which cited URLs were actually retrieved. */
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

export interface CostEstimate {
  model: string;
  expected_usd: number;
  low_usd: number;
  high_usd: number;
  expected_searches: number;
  expected_turns: number;
  priced: boolean;
}

export interface EventsPage {
  task_id: string;
  status: TaskStatus;
  cursor: number;
  events: TaskEvent[];
  searches_used: number;
  actual_cost_usd: number;
  done: boolean;
}

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

export interface PublicReport {
  query: string;
  report_markdown: string;
  created_at: string;
  sources: Source[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

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

/** Calls the backend through the same-origin authenticated proxy. */
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

/** Calls a route handler on this app (session cookie handling, not the API). */
async function local<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) await parseError(res, `Request failed (${res.status})`);
  return (await res.json()) as T;
}

export const api = {
  auth: {
    async register(email: string, password: string): Promise<void> {
      await local("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
    },
    async login(email: string, password: string): Promise<void> {
      await local("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
    },
    async logout(): Promise<void> {
      await local("/api/auth/logout", { method: "POST" });
    },
    async me(): Promise<User> {
      return request<User>("/api/auth/me");
    },
    async deleteAccount(): Promise<void> {
      await request<void>("/api/auth/me", { method: "DELETE" });
    },
  },
  tasks: {
    async create(query: string): Promise<TaskDetail> {
      return request<TaskDetail>("/api/tasks", {
        method: "POST",
        body: JSON.stringify({ query }),
      });
    },
    async list(): Promise<TaskSummary[]> {
      return request<TaskSummary[]>("/api/tasks");
    },
    async get(taskId: string): Promise<TaskDetail> {
      return request<TaskDetail>(`/api/tasks/${taskId}`);
    },
    /** Incremental progress: only events newer than `after`. */
    async events(taskId: string, after: number): Promise<EventsPage> {
      return request<EventsPage>(`/api/tasks/${taskId}/events?after=${after}`);
    },
    /** What running the current plan is expected to cost. */
    async estimate(taskId: string): Promise<CostEstimate> {
      return request<CostEstimate>(`/api/tasks/${taskId}/estimate`);
    },
    /** Price a plan the user is still editing, before they commit to it. */
    async estimateFor(taskId: string, plan: string[]): Promise<CostEstimate> {
      return request<CostEstimate>(`/api/tasks/${taskId}/estimate`, {
        method: "POST",
        body: JSON.stringify({ plan }),
      });
    },
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
    async cancel(taskId: string): Promise<TaskDetail> {
      return request<TaskDetail>(`/api/tasks/${taskId}/cancel`, { method: "POST" });
    },
    async toggleSource(taskId: string, sourceId: string): Promise<Source> {
      return request<Source>(`/api/tasks/${taskId}/sources/${sourceId}/toggle`, {
        method: "POST",
      });
    },
    async toggleShare(taskId: string): Promise<TaskDetail> {
      return request<TaskDetail>(`/api/tasks/${taskId}/share`, { method: "POST" });
    },
    pdfUrl(taskId: string): string {
      return `/api/proxy/api/tasks/${taskId}/pdf`;
    },
  },
  public: {
    async getReport(shareId: string): Promise<PublicReport> {
      const res = await fetch(`/api/share/${shareId}`, { cache: "no-store" });
      if (!res.ok) await parseError(res, "Report not found");
      return (await res.json()) as PublicReport;
    },
  },
};

/** Pulls a human-readable message off an unknown thrown value. */
export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

/** Formats a dollar amount for amounts that are usually well under $1. */
export function formatUsd(amount: number | null | undefined): string {
  if (amount == null) return "—";
  if (amount === 0) return "$0.00";
  if (amount < 0.01) return `<$0.01`;
  return `$${amount.toFixed(2)}`;
}
