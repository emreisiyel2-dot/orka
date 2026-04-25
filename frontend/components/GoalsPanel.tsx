"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { Goal, GoalProgress } from "@/lib/types";

interface GoalsPanelProps {
  projectId: string;
}

const STATUS_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  planned: { label: "Planned", color: "text-zinc-400", bg: "bg-zinc-800" },
  active: { label: "Active", color: "text-blue-400", bg: "bg-blue-400/10" },
  completed: { label: "Completed", color: "text-emerald-400", bg: "bg-emerald-400/10" },
  paused: { label: "Paused", color: "text-yellow-400", bg: "bg-yellow-400/10" },
  abandoned: { label: "Abandoned", color: "text-red-400", bg: "bg-red-400/10" },
};

export default function GoalsPanel({ projectId }: GoalsPanelProps) {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [progressMap, setProgressMap] = useState<Record<string, GoalProgress>>({});
  const [loading, setLoading] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchGoals = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getGoals(projectId);
      setGoals(data);
      const progEntries = await Promise.all(
        data.map(async (g) => {
          try {
            const p = await api.getGoalProgress(g.id);
            return [g.id, p] as const;
          } catch {
            return [g.id, null] as const;
          }
        })
      );
      const map: Record<string, GoalProgress> = {};
      for (const [id, p] of progEntries) {
        if (p) map[id] = p;
      }
      setProgressMap(map);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchGoals();
  }, [fetchGoals]);

  async function handleCreate() {
    if (!newTitle.trim()) return;
    try {
      await api.createGoal(projectId, { title: newTitle.trim() });
      setNewTitle("");
      await fetchGoals();
    } catch {
      // silent
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">Goals</h3>
        <button
          onClick={fetchGoals}
          disabled={loading}
          className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          Refresh
        </button>
      </div>

      <div className="flex gap-2">
        <input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          placeholder="New goal..."
          className="flex-1 px-3 py-1.5 rounded-lg bg-base-50 border border-border text-sm text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-border-light"
        />
        <button
          onClick={handleCreate}
          disabled={!newTitle.trim()}
          className="px-3 py-1.5 rounded-lg bg-blue-600 text-sm text-white font-medium hover:bg-blue-500 transition-colors disabled:opacity-40"
        >
          Add
        </button>
      </div>

      {loading && goals.length === 0 && (
        <p className="text-xs text-zinc-500">Loading goals...</p>
      )}

      {!loading && goals.length === 0 && (
        <p className="text-xs text-zinc-600">No goals yet. Create one above.</p>
      )}

      <div className="space-y-2">
        {goals.map((goal) => {
          const style = STATUS_STYLES[goal.status] || STATUS_STYLES.planned;
          const progress = progressMap[goal.id];
          const isExpanded = expandedId === goal.id;

          return (
            <div key={goal.id} className="rounded-lg border border-border bg-base-50 overflow-hidden">
              <button
                onClick={() => setExpandedId(isExpanded ? null : goal.id)}
                className="w-full px-3 py-2.5 flex items-center gap-3 text-left hover:bg-base-100 transition-colors"
              >
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${style.color} ${style.bg}`}>
                  {style.label}
                </span>
                <span className="flex-1 text-sm text-zinc-300 truncate">{goal.title}</span>
                {progress && (
                  <span className="text-xs text-zinc-500">{progress.progress_percent}%</span>
                )}
              </button>

              {isExpanded && (
                <div className="px-3 pb-3 space-y-2 border-t border-border">
                  {goal.description && (
                    <p className="text-xs text-zinc-500 pt-2">{goal.description}</p>
                  )}

                  {progress && (
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs text-zinc-500">
                        <span>{progress.completed_tasks}/{progress.total_tasks} tasks</span>
                        <span>{progress.progress_percent}%</span>
                      </div>
                      <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-emerald-500 rounded-full transition-all"
                          style={{ width: `${progress.progress_percent}%` }}
                        />
                      </div>
                    </div>
                  )}

                  <div className="flex gap-2 pt-1">
                    {goal.status !== "completed" && (
                      <button
                        onClick={async () => {
                          try {
                            await api.updateGoal(goal.id, { status: "completed" });
                            await fetchGoals();
                          } catch { /* silent */ }
                        }}
                        className="text-xs px-2 py-1 rounded bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/30 transition-colors"
                      >
                        Complete
                      </button>
                    )}
                    {goal.status === "active" && (
                      <button
                        onClick={async () => {
                          try {
                            await api.updateGoal(goal.id, { status: "paused" });
                            await fetchGoals();
                          } catch { /* silent */ }
                        }}
                        className="text-xs px-2 py-1 rounded bg-yellow-600/20 text-yellow-400 hover:bg-yellow-600/30 transition-colors"
                      >
                        Pause
                      </button>
                    )}
                    {goal.status === "paused" && (
                      <button
                        onClick={async () => {
                          try {
                            await api.updateGoal(goal.id, { status: "active" });
                            await fetchGoals();
                          } catch { /* silent */ }
                        }}
                        className="text-xs px-2 py-1 rounded bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 transition-colors"
                      >
                        Resume
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
