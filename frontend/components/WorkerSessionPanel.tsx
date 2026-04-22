"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { WorkerSession, WorkerLog, AutonomousDecision } from "@/lib/types";
import AutonomousDecisionFeed from "./AutonomousDecisionFeed";

interface WorkerSessionPanelProps {
  projectId: string;
}

const SESSION_STATUS_CONFIG: Record<
  WorkerSession["status"],
  { label: string; dot: string; bg: string; text: string; pulse: boolean }
> = {
  idle: { label: "Idle", dot: "bg-zinc-500", bg: "bg-zinc-800", text: "text-zinc-400", pulse: false },
  running: { label: "Running", dot: "bg-working", bg: "bg-working/10", text: "text-working", pulse: false },
  waiting_input: { label: "Waiting Input", dot: "bg-error", bg: "bg-error/10", text: "text-error", pulse: true },
  completed: { label: "Completed", dot: "bg-healthy", bg: "bg-healthy/10", text: "text-healthy", pulse: false },
  error: { label: "Error", dot: "bg-error", bg: "bg-error/10", text: "text-error", pulse: false },
};

const LOG_LEVEL_COLORS: Record<WorkerLog["level"], string> = {
  info: "text-info",
  warn: "text-working",
  error: "text-error",
  output: "text-zinc-300",
};

export default function WorkerSessionPanel({ projectId }: WorkerSessionPanelProps) {
  const [sessions, setSessions] = useState<WorkerSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  const [sessionLogs, setSessionLogs] = useState<WorkerLog[]>([]);
  const [sessionDecisions, setSessionDecisions] = useState<AutonomousDecision[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [inputText, setInputText] = useState("");
  const [sendingInput, setSendingInput] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      const data = await api.getSessions(projectId);
      setSessions(data);
    } catch {
      // silent refresh failure
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    const interval = setInterval(() => {
      loadSessions();
    }, 5000);
    return () => clearInterval(interval);
  }, [loadSessions]);

  async function handleExpandSession(sessionId: string) {
    if (expandedSessionId === sessionId) {
      setExpandedSessionId(null);
      setSessionLogs([]);
      setSessionDecisions([]);
      return;
    }

    setExpandedSessionId(sessionId);
    setLogsLoading(true);

    try {
      const [logs, decisions] = await Promise.all([
        api.getSessionLogs(sessionId),
        api.getSessionDecisions(sessionId),
      ]);
      setSessionLogs(logs);
      setSessionDecisions(decisions);
    } catch {
      // logs may not be available
      setSessionLogs([]);
      setSessionDecisions([]);
    } finally {
      setLogsLoading(false);
    }
  }

  async function handleSendInput(sessionId: string, inputValue: string) {
    setSendingInput(sessionId);
    try {
      await api.sendSessionInput(sessionId, inputValue);
      setInputText("");
      await loadSessions();
    } catch {
      // input send failure
    } finally {
      setSendingInput(null);
    }
  }

  async function handleCancel(sessionId: string) {
    try {
      await api.cancelSession(sessionId);
      await loadSessions();
    } catch (err) {
      console.error('Cancel failed:', err);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 border-2 border-info border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-zinc-500">Loading sessions...</span>
        </div>
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="bg-base-50 border border-border rounded-lg p-6 text-center">
        <p className="text-zinc-500 text-sm">No active worker sessions</p>
        <p className="text-zinc-600 text-xs mt-1">
          Sessions will appear when workers pick up tasks
        </p>
      </div>
    );
  }

  // Collect all auto-resolved decisions count across sessions
  const totalAutoResolved = sessions.reduce((acc, s) => acc + (s.status === "completed" ? 1 : 0), 0);

  return (
    <div className="space-y-3">
      {/* Session count summary */}
      {totalAutoResolved > 0 && (
        <div className="flex items-center gap-2 mb-2">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-healthy/10 text-healthy">
            {totalAutoResolved} Auto-resolved
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {sessions.map((session) => {
          const statusConfig = SESSION_STATUS_CONFIG[session.status];
          const isExpanded = expandedSessionId === session.id;
          const isSending = sendingInput === session.id;

          return (
            <div
              key={session.id}
              className="bg-base-50 border border-border rounded-lg overflow-hidden"
            >
              {/* Card Header - Clickable */}
              <button
                onClick={() => handleExpandSession(session.id)}
                className="w-full text-left px-4 py-3 hover:bg-base-100/50 transition-colors"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div
                      className={`w-2 h-2 rounded-full ${statusConfig.dot} ${
                        statusConfig.pulse ? "animate-pulse" : ""
                      }`}
                    />
                    <span
                      className={`text-[11px] font-medium uppercase tracking-wider ${statusConfig.text}`}
                    >
                      {statusConfig.label}
                    </span>
                  </div>
                  <span className="text-[11px] text-zinc-600">
                    {relativeTime(session.updated_at)}
                  </span>
                </div>

                {session.last_output && (
                  <p className="text-xs text-zinc-400 line-clamp-2">
                    {session.last_output}
                  </p>
                )}

                <p className="text-[11px] text-zinc-600 mt-1">
                  Created {relativeTime(session.created_at)}
                </p>
              </button>

              {/* Input Required Section */}
              {session.waiting_for_input && (
                <div className="px-4 pb-3 border-t border-border pt-3">
                  {session.input_prompt_text && (
                    <p className="text-xs text-zinc-300 mb-2">
                      {session.input_prompt_text}
                    </p>
                  )}

                  {session.input_type === "enter" && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleSendInput(session.id, "")}
                        disabled={isSending}
                        className="flex-1 px-3 py-1.5 rounded-md bg-error/10 text-error text-xs font-medium hover:bg-error/20 transition-colors disabled:opacity-50"
                      >
                        {isSending ? "Sending..." : "Press Enter"}
                      </button>
                      <button
                        onClick={() => handleCancel(session.id)}
                        className="px-3 py-1.5 rounded-md bg-error/10 text-error text-xs font-medium hover:bg-error/20 transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  )}

                  {session.input_type === "yes_no" && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleSendInput(session.id, "y")}
                        disabled={isSending}
                        className="flex-1 px-3 py-1.5 rounded-md bg-healthy/10 text-healthy text-xs font-medium hover:bg-healthy/20 transition-colors disabled:opacity-50"
                      >
                        Yes
                      </button>
                      <button
                        onClick={() => handleSendInput(session.id, "n")}
                        disabled={isSending}
                        className="flex-1 px-3 py-1.5 rounded-md bg-error/10 text-error text-xs font-medium hover:bg-error/20 transition-colors disabled:opacity-50"
                      >
                        No
                      </button>
                      <button
                        onClick={() => handleCancel(session.id)}
                        className="px-3 py-1.5 rounded-md bg-error/10 text-error text-xs font-medium hover:bg-error/20 transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  )}

                  {session.input_type === "text" && (
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={inputText}
                        onChange={(e) => setInputText(e.target.value)}
                        placeholder="Type response..."
                        className="flex-1 bg-base border border-border rounded-md px-3 py-1.5 text-xs text-zinc-200 placeholder-zinc-600 focus:border-info focus:ring-0 outline-none transition-colors"
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && inputText.trim()) {
                            handleSendInput(session.id, inputText.trim());
                          }
                        }}
                      />
                      <button
                        onClick={() => handleSendInput(session.id, inputText.trim())}
                        disabled={isSending || !inputText.trim()}
                        className="px-3 py-1.5 rounded-md bg-info/10 text-info text-xs font-medium hover:bg-info/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Send
                      </button>
                      <button
                        onClick={() => handleCancel(session.id)}
                        className="px-3 py-1.5 rounded-md bg-error/10 text-error text-xs font-medium hover:bg-error/20 transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Cancel button for running sessions */}
              {(session.status === "running" && !session.waiting_for_input) && (
                <div className="px-4 pb-3 border-t border-border pt-3">
                  <button
                    onClick={() => handleCancel(session.id)}
                    className="w-full px-3 py-1.5 rounded-md bg-error/10 text-error text-xs font-medium hover:bg-error/20 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              )}

              {/* Expanded Logs Section */}
              {isExpanded && (
                <div className="border-t border-border">
                  {/* Logs */}
                  <div className="px-4 py-3">
                    <p className="text-[11px] text-zinc-500 font-medium uppercase tracking-wider mb-2">
                      Recent Logs
                    </p>
                    {logsLoading ? (
                      <div className="flex items-center gap-2 py-2">
                        <div className="w-3 h-3 border-2 border-zinc-500 border-t-transparent rounded-full animate-spin" />
                        <span className="text-xs text-zinc-500">Loading...</span>
                      </div>
                    ) : sessionLogs.length === 0 ? (
                      <p className="text-xs text-zinc-600">No logs available</p>
                    ) : (
                      <div className="max-h-48 overflow-y-auto space-y-1">
                        {sessionLogs.slice(0, 20).map((log) => (
                          <div key={log.id} className="flex items-start gap-2">
                            <span
                              className={`text-[10px] font-medium uppercase shrink-0 mt-0.5 ${LOG_LEVEL_COLORS[log.level]}`}
                            >
                              {log.level}
                            </span>
                            <p className="text-xs text-zinc-400 break-all">
                              {log.content}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Decisions */}
                  {sessionDecisions.length > 0 && (
                    <div className="px-4 py-3 border-t border-border">
                      <p className="text-[11px] text-zinc-500 font-medium uppercase tracking-wider mb-2">
                        Autonomous Decisions ({sessionDecisions.length})
                      </p>
                      <AutonomousDecisionFeed decisions={sessionDecisions} />
                    </div>
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

function relativeTime(timestamp: string): string {
  try {
    const now = Date.now();
    const then = new Date(timestamp).getTime();
    const diffMs = now - then;

    if (diffMs < 0) return "just now";

    const seconds = Math.floor(diffMs / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (seconds < 60) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;

    return new Date(timestamp).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}
