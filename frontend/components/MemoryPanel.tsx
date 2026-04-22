"use client";

import type { MemorySnapshot } from "@/lib/types";

interface MemoryPanelProps {
  memory: MemorySnapshot | null;
}

export default function MemoryPanel({ memory }: MemoryPanelProps) {
  if (!memory) {
    return (
      <div className="bg-base-50 border border-border rounded-lg p-5 text-center">
        <p className="text-zinc-500 text-sm">No memory snapshot yet</p>
        <p className="text-zinc-600 text-xs mt-1">
          Memory will appear after the first task is processed
        </p>
      </div>
    );
  }

  return (
    <div className="bg-base-50 border border-border rounded-lg divide-y divide-border">
      <MemorySection
        label="Last Completed"
        value={memory.last_completed}
        color="text-healthy"
        emptyText="Nothing completed yet"
      />
      <MemorySection
        label="Current Blocker"
        value={memory.current_blocker}
        color="text-error"
        emptyText="No blockers"
      />
      <MemorySection
        label="Next Step"
        value={memory.next_step}
        color="text-info"
        emptyText="No next step defined"
      />
    </div>
  );
}

function MemorySection({
  label,
  value,
  color,
  emptyText,
}: {
  label: string;
  value: string;
  color: string;
  emptyText: string;
}) {
  const isEmpty = !value || value.trim() === "" || value === "none";

  return (
    <div className="px-4 py-3">
      <p className="text-[11px] text-zinc-500 font-medium uppercase tracking-wider mb-1">
        {label}
      </p>
      {isEmpty ? (
        <p className="text-xs text-zinc-600">{emptyText}</p>
      ) : (
        <p className={`text-sm ${color}`}>{value}</p>
      )}
    </div>
  );
}
