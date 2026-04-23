"use client";

import { useState } from "react";
import type { BrainstormMessage } from "@/lib/types";

type Props = {
  messages: BrainstormMessage[];
  onSendMessage: (content: string, targetAgentType?: string) => void;
  disabled?: boolean;
};

const AGENT_COLORS: Record<string, string> = {
  orchestrator: "text-info border-info/30",
  backend: "text-healthy border-healthy/30",
  frontend: "text-purple-400 border-purple-400/30",
  qa: "text-error border-error/30",
  docs: "text-amber-400 border-amber-400/30",
  memory: "text-cyan-400 border-cyan-400/30",
};

const AGENT_BG: Record<string, string> = {
  orchestrator: "bg-info/5",
  backend: "bg-healthy/5",
  frontend: "bg-purple-400/5",
  qa: "bg-error/5",
  docs: "bg-amber-400/5",
  memory: "bg-cyan-400/5",
};

const TYPE_LABELS: Record<string, string> = {
  analysis: "Analysis",
  question: "Question",
  risk: "Risk",
  suggestion: "Suggestion",
  plan: "Plan",
  challenge: "Challenge",
  response: "Response",
  idea: "Idea",
};

const AGENT_DISPLAY: Record<string, string> = {
  orchestrator: "Orchestrator",
  backend: "Backend",
  frontend: "Frontend",
  qa: "QA",
  docs: "Docs",
  memory: "Memory",
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

export default function BrainstormChat({ messages, onSendMessage, disabled }: Props) {
  const [input, setInput] = useState("");
  const [targetAgent, setTargetAgent] = useState<string>("");

  function handleSubmit() {
    if (!input.trim() || disabled) return;
    onSendMessage(input.trim(), targetAgent || undefined);
    setInput("");
    setTargetAgent("");
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1 pb-4">
        {messages.length === 0 && (
          <div className="text-center py-12 text-zinc-500 text-sm">
            No messages yet. Start the discussion!
          </div>
        )}
        {messages.map((msg) => {
          const isUser = msg.role === "user";
          const isSystem = msg.role === "system";
          const agentType = msg.agent_type || "orchestrator";
          const colorClass = AGENT_COLORS[agentType] || AGENT_COLORS.orchestrator;
          const bgClass = AGENT_BG[agentType] || "";

          return (
            <div
              key={msg.id}
              className={`rounded-lg border p-3 ${
                isUser
                  ? "bg-info/5 border-info/20 ml-8"
                  : isSystem
                  ? "bg-zinc-800/50 border-zinc-700 mx-4"
                  : `${bgClass} ${colorClass.split(" ")[1] || "border-border"}`
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                {isUser ? (
                  <span className="text-xs font-medium text-info">You</span>
                ) : isSystem ? (
                  <span className="text-xs font-medium text-zinc-400">System</span>
                ) : (
                  <span className={`text-xs font-medium ${colorClass.split(" ")[0]}`}>
                    {AGENT_DISPLAY[agentType] || agentType}
                  </span>
                )}
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">
                  {TYPE_LABELS[msg.message_type] || msg.message_type}
                </span>
                <span className="text-[10px] text-zinc-600 ml-auto">
                  R{msg.round_number} · {relativeTime(msg.created_at)}
                </span>
              </div>
              <p className="text-sm text-zinc-300 leading-relaxed">{msg.content}</p>
            </div>
          );
        })}
      </div>

      {/* Input */}
      <div className="border-t border-border pt-3 mt-auto">
        <div className="flex gap-2">
          <select
            value={targetAgent}
            onChange={(e) => setTargetAgent(e.target.value)}
            className="bg-zinc-800 border border-border rounded-lg px-2 py-2 text-xs text-zinc-400 focus:outline-none"
          >
            <option value="">All agents</option>
            <option value="orchestrator">Orchestrator</option>
            <option value="backend">Backend</option>
            <option value="frontend">Frontend</option>
            <option value="qa">QA</option>
            <option value="docs">Docs</option>
            <option value="memory">Memory</option>
          </select>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            placeholder={disabled ? "Room is locked..." : "Type a message or question..."}
            disabled={disabled}
            className="flex-1 bg-base-50 border border-border rounded-lg px-4 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-info/50 disabled:opacity-50"
          />
          <button
            onClick={handleSubmit}
            disabled={disabled || !input.trim()}
            className="px-4 py-2 rounded-lg bg-info text-white text-sm font-medium hover:bg-info/90 transition-colors disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
