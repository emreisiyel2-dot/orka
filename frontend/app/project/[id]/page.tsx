"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Project, Task, Agent, ActivityLog, MemorySnapshot } from "@/lib/types";
import AgentCard from "@/components/AgentCard";
import TaskInput from "@/components/TaskInput";
import ActivityFeed from "@/components/ActivityFeed";
import MemoryPanel from "@/components/MemoryPanel";
import SummaryPanel from "@/components/SummaryPanel";
import WorkerSessionPanel from "@/components/WorkerSessionPanel";
import CollaborationPanel from "@/components/CollaborationPanel";

const REFRESH_INTERVAL = 5000;

export default function ProjectDashboard() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;

  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [activities, setActivities] = useState<ActivityLog[]>([]);
  const [memory, setMemory] = useState<MemorySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProject = useCallback(async () => {
    try {
      const data = await api.getProject(projectId);
      setProject(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load project");
    }
  }, [projectId]);

  const loadAgents = useCallback(async () => {
    try {
      const data = await api.getAgents();
      setAgents(data);
    } catch {
      // silent refresh failure
    }
  }, []);

  const loadTasks = useCallback(async () => {
    try {
      const data = await api.getTasks(projectId);
      setTasks(data);
    } catch {
      // silent refresh failure
    }
  }, [projectId]);

  const loadActivity = useCallback(async () => {
    try {
      const data = await api.getActivity(projectId);
      setActivities(data);
    } catch {
      // silent refresh failure
    }
  }, [projectId]);

  const loadMemory = useCallback(async () => {
    try {
      const data = await api.getMemory(projectId);
      setMemory(data);
    } catch {
      // memory might not exist yet
    }
  }, [projectId]);

  // Initial load
  useEffect(() => {
    async function initialLoad() {
      setLoading(true);
      await Promise.all([loadProject(), loadAgents(), loadTasks(), loadActivity(), loadMemory()]);
      setLoading(false);
    }
    initialLoad();
  }, [loadProject, loadAgents, loadTasks, loadActivity, loadMemory]);

  // Auto-refresh agents and activity every 5 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      loadAgents();
      loadActivity();
      loadTasks();
    }, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [loadAgents, loadActivity, loadTasks]);

  async function handleTaskSubmitted() {
    await Promise.all([loadTasks(), loadActivity(), loadAgents()]);
  }

  async function handleDistribute(taskId: string) {
    try {
      await api.distributeTask(taskId);
      await Promise.all([loadTasks(), loadActivity(), loadAgents()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to distribute task");
    }
  }

  async function handleComplete(taskId: string) {
    try {
      await api.completeTask(taskId);
      await Promise.all([loadTasks(), loadActivity(), loadAgents(), loadMemory()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to complete task");
    }
  }

  async function handleRetry(taskId: string) {
    try {
      await api.retryTask(taskId);
      await Promise.all([loadTasks(), loadActivity()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to retry task");
    }
  }

  function getTaskForAgent(agent: Agent): Task | undefined {
    if (!agent.current_task_id) return undefined;
    return tasks.find((t) => t.id === agent.current_task_id);
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 border-2 border-info border-t-transparent rounded-full animate-spin" />
          <span className="text-zinc-400">Loading project...</span>
        </div>
      </div>
    );
  }

  if (error && !project) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <div className="w-12 h-12 rounded-full bg-error/10 flex items-center justify-center">
          <span className="text-error text-xl">!</span>
        </div>
        <p className="text-zinc-400 text-sm">{error}</p>
        <button
          onClick={() => router.push("/")}
          className="text-sm text-info hover:text-info/80 transition-colors"
        >
          Back to Projects
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-4 sm:px-6 py-4">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/")}
              className="text-zinc-500 hover:text-zinc-300 transition-colors text-sm flex items-center gap-1"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="m15 18-6-6 6-6" />
              </svg>
              Back
            </button>
            <div className="w-px h-5 bg-border" />
            <h1 className="text-lg font-semibold truncate">
              {project?.name || "Project"}
            </h1>
          </div>
          {error && (
            <span className="text-xs text-error hidden sm:inline">{error}</span>
          )}
        </div>
      </header>

      {/* Task Input */}
      <div className="border-b border-border px-4 sm:px-6 py-3">
        <div className="max-w-[1600px] mx-auto">
          <TaskInput projectId={projectId} onSubmit={handleTaskSubmitted} />
        </div>
      </div>

      {/* Main Grid */}
      <main className="flex-1 px-4 sm:px-6 py-6 overflow-hidden">
        <div className="max-w-[1600px] mx-auto grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Column 1: Agent Cards */}
          <section>
            <h2 className="text-sm font-medium text-zinc-400 mb-3 uppercase tracking-wider">
              Agents
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-2 gap-3">
              {agents.map((agent) => (
                <AgentCard key={agent.id} agent={agent} task={getTaskForAgent(agent)} />
              ))}
              {agents.length === 0 && (
                <div className="col-span-2 text-center py-8 text-zinc-500 text-sm">
                  No agents connected
                </div>
              )}
            </div>
          </section>

          {/* Column 2: Activity Feed */}
          <section className="min-h-0">
            <h2 className="text-sm font-medium text-zinc-400 mb-3 uppercase tracking-wider">
              Activity Feed
            </h2>
            <ActivityFeed activities={activities} />
          </section>

          {/* Column 3: Memory + Summary + Collaboration */}
          <section className="space-y-4">
            <h2 className="text-sm font-medium text-zinc-400 mb-3 uppercase tracking-wider">
              Memory
            </h2>
            <MemoryPanel memory={memory} />
            <SummaryPanel projectId={projectId} />
            <div className="border-t border-border pt-4">
              <h2 className="text-sm font-medium text-zinc-400 mb-3 uppercase tracking-wider">
                Collaboration
              </h2>
              <CollaborationPanel projectId={projectId} />
            </div>
          </section>
        </div>
      </main>

      {/* Worker Sessions Section */}
      <section className="border-t border-border px-4 sm:px-6 py-6">
        <div className="max-w-[1600px] mx-auto">
          <h2 className="text-sm font-medium text-zinc-400 mb-4 uppercase tracking-wider">
            Worker Sessions
          </h2>
          <WorkerSessionPanel projectId={projectId} />
        </div>
      </section>

      {/* Tasks Section */}
      <section className="border-t border-border px-4 sm:px-6 py-6">
        <div className="max-w-[1600px] mx-auto">
          <h2 className="text-sm font-medium text-zinc-400 mb-4 uppercase tracking-wider">
            Tasks ({tasks.length})
          </h2>
          {tasks.length === 0 ? (
            <div className="text-center py-8 text-zinc-500 text-sm">
              No tasks yet. Submit a task above to get started.
            </div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
              {tasks.map((task) => (
                <div
                  key={task.id}
                  className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 bg-base-50 border border-border rounded-lg px-4 py-3"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm truncate">{task.content}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <StatusBadge status={task.status} />
                      {task.assigned_agent_id && (
                        <span className="text-xs text-zinc-500">
                          Assigned to agent
                        </span>
                      )}
                      {task.retry_count > 0 && (
                        <span className="text-xs text-zinc-500">Retry #{task.retry_count}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {task.status === "pending" && (
                      <button
                        onClick={() => handleDistribute(task.id)}
                        className="text-xs px-3 py-1.5 rounded-md bg-info/10 text-info hover:bg-info/20 transition-colors"
                      >
                        Distribute
                      </button>
                    )}
                    {(task.status === "in_progress" || task.status === "assigned") && (
                      <button
                        onClick={() => handleComplete(task.id)}
                        className="text-xs px-3 py-1.5 rounded-md bg-healthy/10 text-healthy hover:bg-healthy/20 transition-colors"
                      >
                        Complete
                      </button>
                    )}
                    {task.status === "failed" && (
                      <button
                        onClick={() => handleRetry(task.id)}
                        className="text-xs px-3 py-1.5 rounded-md bg-assigned/10 text-assigned hover:bg-assigned/20 transition-colors"
                      >
                        Retry
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function StatusBadge({ status }: { status: Task["status"] }) {
  const config: Record<
    Task["status"],
    { label: string; bg: string; text: string }
  > = {
    pending: { label: "Pending", bg: "bg-zinc-800", text: "text-zinc-400" },
    assigned: { label: "Assigned", bg: "bg-assigned/10", text: "text-assigned" },
    in_progress: { label: "In Progress", bg: "bg-working/10", text: "text-working" },
    completed: { label: "Completed", bg: "bg-healthy/10", text: "text-healthy" },
    failed: { label: "Failed", bg: "bg-error/10", text: "text-error" },
  };

  const c = config[status];

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${c.bg} ${c.text}`}
    >
      {c.label}
    </span>
  );
}
