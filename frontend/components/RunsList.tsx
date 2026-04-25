"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { Run, RunEvent } from "@/lib/types";

interface RunsListProps {
  projectId: string;
}

const STATUS_STYLES: Record<string, { dot: string; color: string; label: string }> = {
  pending: { dot: "bg-zinc-500", color: "text-zinc-500", label: "Pending" },
  running: { dot: "bg-blue-400 animate-pulse", color: "text-blue-400", label: "Running" },
  completed: { dot: "bg-emerald-400", color: "text-emerald-400", label: "Done" },
  failed: { dot: "bg-red-400", color: "text-red-400", label: "Failed" },
  retrying: { dot: "bg-yellow-400", color: "text-yellow-400", label: "Retrying" },
  cancelled: { dot: "bg-zinc-600", color: "text-zinc-600", label: "Cancelled" },
  blocked: { dot: "bg-orange-400", color: "text-orange-400", label: "Blocked" },
  paused: { dot: "bg-yellow-500", color: "text-yellow-500", label: "Paused" },
};

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

export default function RunsList({ projectId }: RunsListProps) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [eventsMap, setEventsMap] = useState<Record<string, RunEvent[]>>({});

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getProjectRuns(projectId);
      setRuns(data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  async function toggleExpand(runId: string) {
    if (expandedId === runId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(runId);
    if (!eventsMap[runId]) {
      try {
        const events = await api.getRunEvents(runId);
        setEventsMap((prev) => ({ ...prev, [runId]: events }));
      } catch {
        // silent
      }
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">Recent Runs</h3>
        <button
          onClick={fetchRuns}
          disabled={loading}
          className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          Refresh
        </button>
      </div>

      {loading && runs.length === 0 && (
        <p className="text-xs text-zinc-500">Loading runs...</p>
      )}

      {!loading && runs.length === 0 && (
        <p className="text-xs text-zinc-600">No runs yet. Runs appear when tasks are executed.</p>
      )}

      <div className="space-y-1.5">
        {runs.slice(0, 20).map((run) => {
          const style = STATUS_STYLES[run.status] || STATUS_STYLES.pending;
          const isExpanded = expandedId === run.id;
          const events = eventsMap[run.id] || [];

          return (
            <div key={run.id} className="rounded-lg border border-border bg-base-50 overflow-hidden">
              <button
                onClick={() => toggleExpand(run.id)}
                className="w-full px-3 py-2 flex items-center gap-3 text-left hover:bg-base-100 transition-colors"
              >
                <span className={`w-2 h-2 rounded-full ${style.dot}`} />
                <span className="text-sm text-zinc-300 flex-1 truncate">
                  {run.agent_type}
                </span>
                <span className="text-xs text-zinc-600 font-mono">
                  {run.execution_mode}
                </span>
                <span className="text-xs text-zinc-600">
                  {run.provider}/{run.model}
                </span>
                <span className="text-xs text-zinc-500">
                  {formatDuration(run.duration_seconds)}
                </span>
                {run.retry_count > 0 && (
                  <span className="text-xs text-yellow-500">
                    x{run.retry_count}
                  </span>
                )}
              </button>

              {isExpanded && (
                <div className="px-3 pb-3 border-t border-border">
                  {run.error_message && (
                    <p className="text-xs text-red-400 pt-2">{run.error_message}</p>
                  )}

                  {events.length > 0 ? (
                    <div className="mt-2 space-y-1">
                      {events.map((evt) => (
                        <div key={evt.id} className="flex items-start gap-2 text-xs">
                          <span className="text-zinc-600 font-mono shrink-0">
                            {new Date(evt.created_at).toLocaleTimeString()}
                          </span>
                          <span className="text-zinc-500 font-medium shrink-0">
                            {evt.event_type}
                          </span>
                          <span className="text-zinc-600 truncate">{evt.message}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-zinc-600 pt-2">No events recorded.</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
