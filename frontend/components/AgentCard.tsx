"use client";

import type { BrainstormAgent } from "@/lib/types";

type Props = {
  agent: BrainstormAgent;
  latestMessageType?: string | null;
};

const AGENT_CONFIG: Record<string, {
  icon: string;
  color: string;
  bg: string;
  border: string;
  desc: string;
}> = {
  orchestrator: {
    icon: "🎯",
    color: "text-info",
    bg: "bg-info/5",
    border: "border-info/20",
    desc: "Coordinates scope & priorities",
  },
  backend: {
    icon: "⚙️",
    color: "text-healthy",
    bg: "bg-healthy/5",
    border: "border-healthy/20",
    desc: "APIs, databases, services",
  },
  frontend: {
    icon: "🎨",
    color: "text-purple-400",
    bg: "bg-purple-400/5",
    border: "border-purple-400/20",
    desc: "UI components & user flows",
  },
  qa: {
    icon: "🔍",
    color: "text-error",
    bg: "bg-error/5",
    border: "border-error/20",
    desc: "Risks, tests, edge cases",
  },
  docs: {
    icon: "📝",
    color: "text-amber-400",
    bg: "bg-amber-400/5",
    border: "border-amber-400/20",
    desc: "Documentation & guides",
  },
  memory: {
    icon: "🧠",
    color: "text-cyan-400",
    bg: "bg-cyan-400/5",
    border: "border-cyan-400/20",
    desc: "Progress tracking & summaries",
  },
};

const STATUS_DISPLAY: Record<string, { label: string; dot: string }> = {
  active: { label: "Active", dot: "bg-healthy" },
  thinking: { label: "Thinking", dot: "bg-info animate-pulse" },
  paused: { label: "Idle", dot: "bg-zinc-500" },
  completed: { label: "Done", dot: "bg-zinc-600" },
};

export default function AgentCard({ agent, latestMessageType }: Props) {
  const config = AGENT_CONFIG[agent.agent_type] || AGENT_CONFIG.orchestrator;
  const statusInfo = STATUS_DISPLAY[agent.status] || STATUS_DISPLAY.paused;

  return (
    <div className={`${config.bg} border ${config.border} rounded-lg p-3 transition-all`}>
      <div className="flex items-start gap-2.5">
        <div className="text-lg leading-none mt-0.5">{config.icon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-1">
            <span className={`text-xs font-semibold ${config.color}`}>
              {agent.agent_name}
            </span>
            <div className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${statusInfo.dot}`} />
              <span className="text-[10px] text-zinc-500">{statusInfo.label}</span>
            </div>
          </div>
          <p className="text-[10px] text-zinc-500 mt-0.5 leading-tight">
            {config.desc}
          </p>
          {latestMessageType && (
            <span className="inline-block mt-1.5 px-1.5 py-0.5 rounded text-[9px] font-medium bg-zinc-800 text-zinc-400">
              {latestMessageType}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
