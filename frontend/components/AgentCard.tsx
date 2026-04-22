"use client";

import type { Agent, Task } from "@/lib/types";

interface AgentCardProps {
  agent: Agent;
  task?: Task;
}

const AGENT_ICONS: Record<Agent["type"], string> = {
  orchestrator: "\u{1F3AF}",
  backend: "\u{2699}\u{FE0F}",
  frontend: "\u{1F3A8}",
  qa: "\u{1F9EA}",
  docs: "\u{1F4D6}",
  memory: "\u{1F9E0}",
};

const AGENT_LABELS: Record<Agent["type"], string> = {
  orchestrator: "Orchestrator",
  backend: "Backend",
  frontend: "Frontend",
  qa: "QA",
  docs: "Docs",
  memory: "Memory",
};

const STATUS_COLORS: Record<Agent["status"], { dot: string; bg: string; text: string }> = {
  idle: { dot: "bg-healthy", bg: "bg-healthy/10", text: "text-healthy" },
  working: { dot: "bg-working", bg: "bg-working/10", text: "text-working" },
  error: { dot: "bg-error", bg: "bg-error/10", text: "text-error" },
};

export default function AgentCard({ agent, task }: AgentCardProps) {
  const statusStyle = STATUS_COLORS[agent.status];
  const icon = AGENT_ICONS[agent.type];
  const label = AGENT_LABELS[agent.type];

  return (
    <div className="bg-base-50 border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-base leading-none">{icon}</span>
          <div>
            <h3 className="text-sm font-medium">{agent.name}</h3>
            <p className="text-[11px] text-zinc-500">{label}</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${statusStyle.dot} ${agent.status === "working" ? "animate-pulse" : ""}`} />
          <span className={`text-[11px] font-medium capitalize ${statusStyle.text}`}>
            {agent.status}
          </span>
        </div>
      </div>

      {task && (
        <div className="mt-2 pt-2 border-t border-border">
          <p className="text-[11px] text-zinc-500 mb-0.5">Current Task</p>
          <p className="text-xs text-zinc-300 truncate">{task.content}</p>
        </div>
      )}

      {!task && agent.status === "idle" && (
        <div className="mt-2 pt-2 border-t border-border">
          <p className="text-[11px] text-zinc-600">No active task</p>
        </div>
      )}
    </div>
  );
}
