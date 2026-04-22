"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Summary } from "@/lib/types";

interface SummaryPanelProps {
  projectId: string;
}

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  healthy: { label: "Healthy", color: "text-healthy", bg: "bg-healthy/10" },
  blocked: { label: "Blocked", color: "text-error", bg: "bg-error/10" },
  idle: { label: "Idle", color: "text-zinc-400", bg: "bg-zinc-800" },
};

export default function SummaryPanel({ projectId }: SummaryPanelProps) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);

  async function fetchSummary() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getSummary(projectId);
      setSummary(data);
      setVisible(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load summary");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button
          onClick={fetchSummary}
          disabled={loading}
          className="px-4 py-2 rounded-lg bg-base-50 border border-border text-sm font-medium text-zinc-300 hover:border-border-light hover:bg-base-100 transition-colors disabled:opacity-50"
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <span className="w-3.5 h-3.5 border-2 border-zinc-400 border-t-transparent rounded-full animate-spin" />
              Loading Summary
            </span>
          ) : (
            "Fetch Summary"
          )}
        </button>
        {visible && summary && (
          <button
            onClick={() => setVisible(!visible)}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            {visible ? "Hide" : "Show"}
          </button>
        )}
      </div>

      {error && (
        <div className="bg-error/5 border border-error/20 rounded-lg px-4 py-3">
          <p className="text-xs text-error">{error}</p>
        </div>
      )}

      {visible && summary && (
        <div className="bg-base-50 border border-border rounded-lg overflow-hidden">
          {/* Overall Status */}
          <div className="px-4 py-3 border-b border-border">
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500 font-medium">Overall Status</span>
              <StatusBadge status={summary.overall_status} />
            </div>
          </div>

          {/* Task Stats */}
          <div className="px-4 py-3 border-b border-border">
            <p className="text-xs text-zinc-500 font-medium mb-2">Task Breakdown</p>
            <div className="grid grid-cols-2 gap-2">
              <StatItem label="Total" value={summary.total_tasks} />
              <StatItem
                label="Completed"
                value={summary.completed_tasks}
                color="text-healthy"
              />
              <StatItem
                label="In Progress"
                value={summary.in_progress_tasks}
                color="text-working"
              />
              <StatItem
                label="Pending"
                value={summary.pending_tasks}
                color="text-zinc-400"
              />
            </div>
          </div>

          {/* Progress Bar */}
          <div className="px-4 py-3 border-b border-border">
            <div className="w-full h-1.5 bg-base rounded-full overflow-hidden">
              <div
                className="h-full bg-healthy rounded-full transition-all duration-500"
                style={{
                  width:
                    summary.total_tasks > 0
                      ? `${(summary.completed_tasks / summary.total_tasks) * 100}%`
                      : "0%",
                }}
              />
            </div>
            <p className="text-[11px] text-zinc-600 mt-1">
              {summary.total_tasks > 0
                ? `${Math.round((summary.completed_tasks / summary.total_tasks) * 100)}% complete`
                : "No tasks"}
            </p>
          </div>

          {/* Agent List */}
          <div className="px-4 py-3 border-b border-border">
            <p className="text-xs text-zinc-500 font-medium mb-2">Agents</p>
            <div className="space-y-1">
              {summary.agents.map((agent, i) => (
                <div key={i} className="flex items-center justify-between">
                  <span className="text-xs text-zinc-300">{agent.name}</span>
                  <span
                    className={`text-[11px] capitalize ${
                      agent.status === "idle"
                        ? "text-healthy"
                        : agent.status === "working"
                        ? "text-working"
                        : "text-error"
                    }`}
                  >
                    {agent.status}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Message */}
          {summary.message && (
            <div className="px-4 py-3">
              <p className="text-xs text-zinc-500 font-medium mb-1">Status Message</p>
              <p className="text-sm text-zinc-300">{summary.message}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.idle;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${config.bg} ${config.color}`}
    >
      {config.label}
    </span>
  );
}

function StatItem({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-zinc-500">{label}</span>
      <span className={`text-sm font-medium ${color || "text-zinc-300"}`}>
        {value}
      </span>
    </div>
  );
}
