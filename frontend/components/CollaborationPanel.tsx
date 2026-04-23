"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { AgentMessage, TaskDependency } from "@/lib/types";

type Props = { projectId: string };

const TYPE_STYLES: Record<string, string> = {
  handoff: "bg-info/10 text-info",
  blocker: "bg-error/10 text-error",
  update: "bg-zinc-700/50 text-zinc-400",
  complete: "bg-healthy/10 text-healthy",
  request_info: "bg-working/10 text-working",
  response: "bg-assigned/10 text-assigned",
};

const TYPE_LABELS: Record<string, string> = {
  handoff: "Handoff",
  blocker: "Blocker",
  update: "Update",
  complete: "Complete",
  request_info: "Request",
  response: "Response",
};

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ago`;
}

export default function CollaborationPanel({ projectId }: Props) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [dependencies, setDependencies] = useState<TaskDependency[]>([]);
  const [blockers, setBlockers] = useState<AgentMessage[]>([]);
  const [handoffs, setHandoffs] = useState<AgentMessage[]>([]);

  const refresh = useCallback(async () => {
    try {
      const [msgs, deps, blks, hoffs] = await Promise.all([
        api.getMessages(projectId),
        api.getProjectDependencies(projectId),
        api.getProjectBlockers(projectId),
        api.getProjectHandoffs(projectId),
      ]);
      setMessages(msgs.slice(0, 10));
      setDependencies(deps);
      setBlockers(blks);
      setHandoffs(hoffs);
    } catch {}
  }, [projectId]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  return (
    <div className="space-y-6">
      {/* Messages */}
      <div>
        <h3 className="text-sm font-medium text-zinc-300 mb-3">Agent Messages</h3>
        {messages.length === 0 ? (
          <p className="text-xs text-zinc-500">No agent messages yet</p>
        ) : (
          <div className="space-y-2">
            {messages.map((m) => (
              <div
                key={m.id}
                className="flex items-start gap-2 bg-base-50 border border-border rounded-lg px-3 py-2"
              >
                <span
                  className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 ${TYPE_STYLES[m.message_type] || TYPE_STYLES.update}`}
                >
                  {TYPE_LABELS[m.message_type] || m.message_type}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-zinc-300 truncate">
                    <span className="text-zinc-400">{m.from_agent_name}</span>
                    <span className="text-zinc-600 mx-1">→</span>
                    <span className="text-zinc-400">{m.to_agent_name}</span>
                  </p>
                  <p className="text-xs text-zinc-500 truncate">{m.content}</p>
                </div>
                <span className="text-[10px] text-zinc-600 shrink-0">
                  {relativeTime(m.created_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Dependencies */}
      <div>
        <h3 className="text-sm font-medium text-zinc-300 mb-3">Task Dependencies</h3>
        {dependencies.length === 0 ? (
          <p className="text-xs text-zinc-500">No task dependencies</p>
        ) : (
          <div className="space-y-1.5">
            {dependencies.map((d) => (
              <div
                key={d.id}
                className="flex items-center gap-2 text-xs bg-base-50 border border-border rounded px-3 py-2"
              >
                <span className="text-zinc-400 truncate flex-1">
                  {d.depends_on_content || d.depends_on_task_id.slice(0, 8)}
                </span>
                <span className="text-zinc-600">→</span>
                <span className="text-zinc-300 truncate flex-1">
                  {d.task_content || d.task_id.slice(0, 8)}
                </span>
                <span
                  className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                    d.status === "satisfied"
                      ? "bg-healthy/10 text-healthy"
                      : "bg-working/10 text-working"
                  }`}
                >
                  {d.status === "satisfied" ? "Done" : "Waiting"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Blockers & Handoffs */}
      <div>
        <h3 className="text-sm font-medium text-zinc-300 mb-3">
          Blockers & Handoffs
        </h3>
        {blockers.length === 0 && handoffs.length === 0 ? (
          <p className="text-xs text-zinc-500">
            No active blockers or pending handoffs
          </p>
        ) : (
          <div className="space-y-1.5">
            {blockers.map((b) => (
              <div
                key={b.id}
                className="flex items-center gap-2 text-xs bg-error/5 border border-error/20 rounded px-3 py-2"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-error shrink-0" />
                <span className="text-error font-medium shrink-0">
                  {b.from_agent_name}:
                </span>
                <span className="text-zinc-400 truncate">{b.content}</span>
              </div>
            ))}
            {handoffs.map((h) => (
              <div
                key={h.id}
                className="flex items-center gap-2 text-xs bg-info/5 border border-info/20 rounded px-3 py-2"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-info shrink-0" />
                <span className="text-info font-medium shrink-0">
                  {h.from_agent_name} → {h.to_agent_name}:
                </span>
                <span className="text-zinc-400 truncate">{h.content}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
