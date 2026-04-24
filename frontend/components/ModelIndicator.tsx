"use client";

const TIER_COLORS: Record<string, string> = {
  low: "bg-blue-100 text-blue-700",
  medium: "bg-purple-100 text-purple-700",
  high: "bg-orange-100 text-orange-700",
};

interface ModelIndicatorProps {
  model: string | null;
  provider: string | null;
  tier?: string;
  simulated?: boolean;
}

export default function ModelIndicator({ model, provider, tier, simulated }: ModelIndicatorProps) {
  if (simulated || !model) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">
        simulated
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${TIER_COLORS[tier || "medium"] || TIER_COLORS.medium}`}>
      {model}
      {provider && <span className="opacity-60">({provider})</span>}
    </span>
  );
}
