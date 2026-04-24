"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ProviderStatus } from "@/lib/types";

const STATUS_COLORS: Record<string, string> = {
  available: "bg-green-500",
  throttled: "bg-yellow-500",
  exhausted: "bg-red-500",
  unavailable: "bg-gray-500",
};

const STATUS_LABELS: Record<string, string> = {
  available: "Available",
  throttled: "Throttled",
  exhausted: "Quota Exhausted",
  unavailable: "Unavailable",
};

function formatResetTime(iso: string | null) {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function QuotaStatus() {
  const [providers, setProviders] = useState<ProviderStatus[]>([]);

  useEffect(() => {
    api.getProviders().then(setProviders).catch(() => {});
  }, []);

  if (providers.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 p-4">
        <h3 className="text-sm font-semibold text-gray-500 mb-1">Provider Quota</h3>
        <p className="text-xs text-gray-400">No providers configured (simulation mode)</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">Provider Quota</h3>
      <div className="space-y-2">
        {providers.map((p) => (
          <div key={p.name} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className={`inline-block w-2 h-2 rounded-full ${STATUS_COLORS[p.quota_status] || STATUS_COLORS.unavailable}`} />
              <span className="font-medium capitalize">{p.name}</span>
            </div>
            <div className="flex items-center gap-3 text-gray-500">
              <span>{STATUS_LABELS[p.quota_status] || p.quota_status}</span>
              {p.remaining_quota != null && p.total_quota != null && (
                <span>{Math.round((p.remaining_quota / p.total_quota) * 100)}%</span>
              )}
              {p.reset_at && p.quota_status === "exhausted" && (
                <span className="text-red-400">resets {formatResetTime(p.reset_at)}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
