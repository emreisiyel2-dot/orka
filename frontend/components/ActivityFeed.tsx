"use client";

import type { ActivityLog } from "@/lib/types";

interface ActivityFeedProps {
  activities: ActivityLog[];
}

export default function ActivityFeed({ activities }: ActivityFeedProps) {
  if (activities.length === 0) {
    return (
      <div className="bg-base-50 border border-border rounded-lg p-6 text-center">
        <p className="text-zinc-500 text-sm">No activity yet</p>
        <p className="text-zinc-600 text-xs mt-1">
          Submit a task to see activity here
        </p>
      </div>
    );
  }

  return (
    <div className="bg-base-50 border border-border rounded-lg overflow-hidden">
      <div className="max-h-[500px] overflow-y-auto">
        <div className="divide-y divide-border">
          {activities.map((activity, index) => (
            <div
              key={activity.id}
              className="px-4 py-3 hover:bg-base-100/50 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    {activity.agent_id && (
                      <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-info/10 text-info">
                        Agent
                      </span>
                    )}
                    <span className="text-sm font-medium text-zinc-300">
                      {activity.action}
                    </span>
                  </div>
                  {activity.details && (
                    <p className="text-xs text-zinc-500 mt-1 line-clamp-2">
                      {activity.details}
                    </p>
                  )}
                </div>
                <span className="text-[11px] text-zinc-600 whitespace-nowrap shrink-0">
                  {relativeTime(activity.timestamp)}
                </span>
              </div>
            </div>
          ))}
        </div>
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
