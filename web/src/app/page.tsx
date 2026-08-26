/** Authenticated dashboard coordinating task creation, approval, and results. */
"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, TaskDetail, TaskSummary, User } from "@/lib/api";
import { AuthModal } from "@/components/AuthModal";
import { LiveResearchTimeline } from "@/components/LiveResearchTimeline";
import { Navbar } from "@/components/Navbar";
import { PlanApprovalGate } from "@/components/PlanApprovalGate";
import { ReportView } from "@/components/ReportView";
import { TaskCreator } from "@/components/TaskCreator";
import { TaskList } from "@/components/TaskList";

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<TaskDetail | null>(null);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [creatingTask, setCreatingTask] = useState(false);
  const [approvingPlan, setApprovingPlan] = useState(false);
  const [cancellingTask, setCancellingTask] = useState(false);
  const [isAuthOpen, setIsAuthOpen] = useState(false);

  const loadTasks = useCallback(async () => {
    setLoadingTasks(true);
    try {
      const list = await api.tasks.list();
      setTasks(list);
    } catch {
      // ignore unauthenticated or network failure
    } finally {
      setLoadingTasks(false);
    }
  }, []);

  // Restore the session on mount. The token is in an httpOnly cookie, so the
  // only way to know whether we are signed in is to ask the API.
  useEffect(() => {
    api.auth
      .me()
      .then((u) => {
        setUser(u);
        void loadTasks();
      })
      .catch(() => setUser(null));
  }, [loadTasks]);

  // Fetch active task details
  const fetchActiveTask = useCallback(async (id: string) => {
    try {
      const detail = await api.tasks.get(id);
      setActiveTask({
        ...detail,
        events: detail.events || [],
        sources: detail.sources || [],
      });
    } catch (err) {
      console.error("Failed to fetch task:", err);
    }
  }, []);

  // Set active task
  const handleSelectTask = (id: string) => {
    setActiveTaskId(id);
    fetchActiveTask(id);
  };

  // Progress polling.
  //
  // Refetching the whole task every tick resends every event and source, so the
  // payload grows for the length of the run. Instead this asks only for events
  // newer than the cursor, and pulls the full task exactly once - when the
  // status changes and there is genuinely new structure to load (a plan to
  // approve, a finished report).
  const cursorRef = useRef(0);
  const lastStatusRef = useRef<string | null>(null);

  useEffect(() => {
    cursorRef.current = 0;
    lastStatusRef.current = null;
  }, [activeTaskId]);

  useEffect(() => {
    if (!activeTaskId) return;

    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const page = await api.tasks.events(activeTaskId, cursorRef.current);
        cursorRef.current = page.cursor;

        // Status transitions are detected outside the state updater: React may
        // call an updater twice in development, which would double-fetch.
        const statusChanged =
          lastStatusRef.current !== null && lastStatusRef.current !== page.status;
        lastStatusRef.current = page.status;

        setActiveTask((current) => {
          if (!current || current.id !== page.task_id) return current;
          const currentEvents = current.events || [];
          const newEvents = page.events || [];
          return {
            ...current,
            status: page.status,
            searches_used: page.searches_used,
            actual_cost_usd: page.actual_cost_usd,
            events: newEvents.length
              ? [...currentEvents, ...newEvents]
              : currentEvents,
            sources: current.sources || [],
          };
        });

        if (statusChanged) {
          // A new plan to approve, or a finished report - load the structure once.
          await fetchActiveTask(activeTaskId);
        }

        setTasks((prev) =>
          prev.map((t) => (t.id === page.task_id ? { ...t, status: page.status } : t)),
        );

        if (page.done) return; // terminal - stop polling entirely
      } catch {
        // Transient failure; the next tick will catch up from the same cursor.
      }

      if (!stopped) timer = setTimeout(tick, 2000);
    };

    timer = setTimeout(tick, 800);

    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [activeTaskId, fetchActiveTask]);

  // Create task
  const handleCreateTask = async (query: string) => {
    if (!user) {
      setIsAuthOpen(true);
      return;
    }
    setCreatingTask(true);
    try {
      const created = await api.tasks.create(query);
      setActiveTaskId(created.id);
      setActiveTask({
        ...created,
        events: [],
        sources: [],
      });
      await loadTasks();
    } catch (err: unknown) {
      alert(errorMessage(err, "Failed to create task"));
    } finally {
      setCreatingTask(false);
    }
  };

  // Approve plan
  const handleApprovePlan = async (
    plan: string[],
    answers: Record<string, string>
  ) => {
    if (!activeTaskId) return;
    setApprovingPlan(true);
    try {
      const updated = await api.tasks.approve(activeTaskId, plan, answers);
      setActiveTask((current) => ({
        ...updated,
        events: current?.events || [],
        sources: current?.sources || [],
      }));
      await loadTasks();
    } catch (err: unknown) {
      alert(errorMessage(err, "Failed to approve plan"));
    } finally {
      setApprovingPlan(false);
    }
  };

  // Cancel task
  const handleCancelTask = async () => {
    if (!activeTaskId) return;
    setCancellingTask(true);
    try {
      const cancelled = await api.tasks.cancel(activeTaskId);
      setActiveTask((current) => ({
        ...cancelled,
        events: current?.events || [],
        sources: current?.sources || [],
      }));
      await loadTasks();
    } catch (err: unknown) {
      alert(errorMessage(err, "Failed to cancel task"));
    } finally {
      setCancellingTask(false);
    }
  };

  // Toggle source exclusion
  const handleToggleSource = async (sourceId: string) => {
    if (!activeTaskId) return;
    try {
      await api.tasks.toggleSource(activeTaskId, sourceId);
      await fetchActiveTask(activeTaskId);
    } catch (err: unknown) {
      alert(errorMessage(err, "Failed to update source"));
    }
  };

  // Toggle public share
  const handleToggleShare = async () => {
    if (!activeTaskId) return;
    try {
      const shared = await api.tasks.toggleShare(activeTaskId);
      setActiveTask((current) => ({
        ...shared,
        events: current?.events || [],
        sources: current?.sources || [],
      }));
    } catch (err: unknown) {
      alert(errorMessage(err, "Failed to toggle share"));
    }
  };

  // Logout
  const handleLogout = () => {
    api.auth.logout();
    setUser(null);
    setTasks([]);
    setActiveTaskId(null);
    setActiveTask(null);
  };

  // Start new task
  const handleNewTask = () => {
    setActiveTaskId(null);
    setActiveTask(null);
  };

  return (
    <div className="flex flex-col min-h-screen bg-zinc-950 text-zinc-100">
      <Navbar
        user={user}
        onOpenAuth={() => setIsAuthOpen(true)}
        onLogout={handleLogout}
        onNewTask={handleNewTask}
      />

      <div className="flex flex-1 flex-col sm:flex-row overflow-hidden">
        {/* Sidebar */}
        <TaskList
          tasks={tasks}
          activeTaskId={activeTaskId}
          onSelectTask={handleSelectTask}
          onNewTask={handleNewTask}
          loading={loadingTasks}
        />

        {/* Main Content Area */}
        <main className="flex-1 overflow-y-auto bg-zinc-950 flex flex-col justify-start">
          {!activeTask ? (
            <TaskCreator
              onSubmit={handleCreateTask}
              loading={creatingTask}
            />
          ) : activeTask.status === "awaiting_approval" ? (
            <PlanApprovalGate
              task={activeTask}
              onApprove={handleApprovePlan}
              onCancel={handleCancelTask}
              loading={approvingPlan}
            />
          ) : activeTask.status === "queued" ||
            activeTask.status === "planning" ||
            activeTask.status === "researching" ? (
            <LiveResearchTimeline
              task={activeTask}
              onCancel={handleCancelTask}
              onToggleSource={handleToggleSource}
              cancelling={cancellingTask}
            />
          ) : activeTask.status === "complete" ? (
            <ReportView
              task={activeTask}
              onToggleShare={handleToggleShare}
              onNewTask={handleNewTask}
            />
          ) : (
            /* Cancelled or Failed State */
            <div className="w-full max-w-3xl mx-auto py-12 px-4">
              <div className="p-6 rounded-2xl bg-zinc-900 border border-zinc-800 text-center">
                <div className="inline-flex p-3 rounded-2xl bg-zinc-800 mb-3 text-2xl">
                  {activeTask.status === "cancelled" ? "🛑" : "⚠️"}
                </div>
                <h2 className="text-xl font-bold text-zinc-100 mb-1 capitalize">
                  Task {activeTask.status}
                </h2>
                <p className="text-xs text-zinc-400 max-w-md mx-auto mb-4">
                  {activeTask.error ||
                    (activeTask.status === "cancelled"
                      ? "This task was cancelled by the user before completion."
                      : "The research agent encountered an error.")}
                </p>
                <button
                  onClick={handleNewTask}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-xl transition-colors cursor-pointer"
                >
                  Start New Investigation
                </button>
              </div>
            </div>
          )}
        </main>
      </div>

      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
        onSuccess={(u) => {
          setUser(u);
          loadTasks();
        }}
      />
    </div>
  );
}
