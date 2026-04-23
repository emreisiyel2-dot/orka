"use client";

import { useState, useRef, useEffect } from "react";
import type { BrainstormMessage } from "@/lib/types";

type Props = {
  messages: BrainstormMessage[];
  onSendMessage: (content: string, targetAgentType?: string) => void;
  disabled?: boolean;
};

const AGENT_COLORS: Record<string, { text: string; bg: string; border: string }> = {
  orchestrator: { text: "text-info", bg: "bg-info/5", border: "border-l-info" },
  backend: { text: "text-healthy", bg: "bg-healthy/5", border: "border-l-healthy" },
  frontend: { text: "text-purple-400", bg: "bg-purple-400/5", border: "border-l-purple-400" },
  qa: { text: "text-error", bg: "bg-error/5", border: "border-l-error" },
  docs: { text: "text-amber-400", bg: "bg-amber-400/5", border: "border-l-amber-400" },
  memory: { text: "text-cyan-400", bg: "bg-cyan-400/5", border: "border-l-cyan-400" },
};

const AGENT_DISPLAY: Record<string, string> = {
  orchestrator: "Orchestrator", backend: "Backend", frontend: "Frontend",
  qa: "QA", docs: "Docs", memory: "Memory",
};

const TYPE_STYLES: Record<string, { label: string; bg: string; text: string }> = {
  analysis: { label: "Analysis", bg: "bg-info/10", text: "text-info" },
  question: { label: "Question", bg: "bg-purple-400/10", text: "text-purple-400" },
  risk: { label: "Risk", bg: "bg-error/10", text: "text-error" },
  suggestion: { label: "Suggestion", bg: "bg-healthy/10", text: "text-healthy" },
  plan: { label: "Plan", bg: "bg-info/10", text: "text-info" },
  challenge: { label: "Challenge", bg: "bg-amber-400/10", text: "text-amber-400" },
  tradeoff: { label: "Trade-off", bg: "bg-amber-400/10", text: "text-amber-400" },
  alternative: { label: "Alternative", bg: "bg-cyan-400/10", text: "text-cyan-400" },
  deep_dive: { label: "Deep Dive", bg: "bg-info/10", text: "text-info" },
  convergence: { label: "Convergence", bg: "bg-healthy/10", text: "text-healthy" },
  synthesis: { label: "Synthesis", bg: "bg-healthy/10", text: "text-healthy" },
  response: { label: "Response", bg: "bg-zinc-700/50", text: "text-zinc-400" },
  idea: { label: "Idea", bg: "bg-info/10", text: "text-info" },
};

function groupByRound(messages: BrainstormMessage[]): Map<number, BrainstormMessage[]> {
  const groups = new Map<number, BrainstormMessage[]>();
  for (const msg of messages) {
    const round = msg.round_number;
    if (!groups.has(round)) groups.set(round, []);
    groups.get(round)!.push(msg);
  }
  return groups;
}

export default function MeetingRoom({ messages, onSendMessage, disabled }: Props) {
  const [input, setInput] = useState("");
  const [targetAgent, setTargetAgent] = useState<string>("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  function handleSubmit() {
    if (!input.trim() || disabled) return;
    onSendMessage(input.trim(), targetAgent || undefined);
    setInput("");
    setTargetAgent("");
  }

  const roundGroups = groupByRound(messages);
  const rounds = Array.from(roundGroups.entries()).sort(([a], [b]) => a - b);

  return (
    <div className="flex flex-col h-full">
      {/* Conversation */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-4 pr-1 pb-4">
        {messages.length === 0 && (
          <div className="text-center py-16 text-zinc-500 text-sm">
            <p className="text-lg mb-2">Meeting Room</p>
            <p className="text-xs">Start the discussion by advancing a round or sending a message</p>
          </div>
        )}

        {rounds.map(([roundNum, roundMsgs]) => (
          <div key={roundNum}>
            {/* Round separator */}
            <div className="flex items-center gap-2 py-2">
              <div className="flex-1 h-px bg-border" />
              <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
                Round {roundNum}
              </span>
              <div className="flex-1 h-px bg-border" />
            </div>

            {/* Messages in this round */}
            <div className="space-y-2">
              {roundMsgs.map((msg) => {
                const isUser = msg.role === "user";
                const isSystem = msg.role === "system";
                const agentType = msg.agent_type || "orchestrator";
                const colors = AGENT_COLORS[agentType] || AGENT_COLORS.orchestrator;
                const typeStyle = TYPE_STYLES[msg.message_type] || TYPE_STYLES.idea;

                return (
                  <div
                    key={msg.id}
                    className={`rounded-lg border-l-2 p-3 ${
                      isUser
                        ? "bg-info/5 border-l-info ml-6"
                        : isSystem
                        ? "bg-zinc-800/50 border-l-zinc-600 mx-4"
                        : `${colors.bg} ${colors.border}`
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className={`text-xs font-semibold ${colors.text}`}>
                        {isUser ? "You" : isSystem ? "System" : AGENT_DISPLAY[agentType] || agentType}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium ${typeStyle.bg} ${typeStyle.text}`}>
                        {typeStyle.label}
                      </span>
                    </div>
                    <p className="text-sm text-zinc-300 leading-relaxed">{msg.content}</p>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="border-t border-border pt-3 mt-auto">
        <div className="flex gap-2">
          <select
            value={targetAgent}
            onChange={(e) => setTargetAgent(e.target.value)}
            className="bg-zinc-800 border border-border rounded-lg px-2 py-2 text-xs text-zinc-400 focus:outline-none shrink-0"
          >
            <option value="">All</option>
            <option value="orchestrator">🎯 Orch.</option>
            <option value="backend">⚙️ Backend</option>
            <option value="frontend">🎨 Frontend</option>
            <option value="qa">🔍 QA</option>
            <option value="docs">📝 Docs</option>
            <option value="memory">🧠 Memory</option>
          </select>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            placeholder={disabled ? "Room is locked..." : "Ask a question or share input..."}
            disabled={disabled}
            className="flex-1 bg-base-50 border border-border rounded-lg px-4 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-info/50 disabled:opacity-50"
          />
          <button
            onClick={handleSubmit}
            disabled={disabled || !input.trim()}
            className="px-4 py-2 rounded-lg bg-info text-white text-sm font-medium hover:bg-info/90 transition-colors disabled:opacity-50 shrink-0"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
