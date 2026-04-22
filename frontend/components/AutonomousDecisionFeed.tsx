"use client";

import type { AutonomousDecision } from "@/lib/types";

interface AutonomousDecisionFeedProps {
  decisions: AutonomousDecision[];
}

export default function AutonomousDecisionFeed({ decisions }: AutonomousDecisionFeedProps) {
  if (decisions.length === 0) {
    return (
      <p className="text-xs text-zinc-600 italic">No autonomous decisions yet</p>
    );
  }

  return (
    <div className="space-y-2">
      {decisions.map((d) => (
        <div
          key={d.id}
          className="bg-base-50 border border-border rounded-lg px-3 py-2"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs text-zinc-300 font-medium truncate">
                  {d.decision}
                </span>
                {d.auto_resolved ? (
                  <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-healthy/10 text-healthy">
                    Auto
                  </span>
                ) : (
                  <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-working/10 text-working">
                    Escalated
                  </span>
                )}
              </div>
              {d.reason && (
                <p className="text-[11px] text-zinc-500 mt-0.5 line-clamp-2">
                  {d.reason}
                </p>
              )}
            </div>
            <span className="text-[11px] text-zinc-600 whitespace-nowrap shrink-0">
              {relativeTime(d.timestamp)}
            </span>
          </div>
        </div>
      ))}
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
