"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { ImprovementProposal, ProposalSummary } from "@/lib/types";
import ProposalCard from "./ProposalCard";

interface ResearchPanelProps {
  projectId: string;
}

const STATUS_TABS = [
  { key: "", label: "All" },
  { key: "draft", label: "Draft" },
  { key: "under_review", label: "Review" },
  { key: "approved", label: "Approved" },
  { key: "converted_to_goal", label: "Converted" },
];

export default function ResearchPanel({ projectId }: ResearchPanelProps) {
  const [proposals, setProposals] = useState<ImprovementProposal[]>([]);
  const [summary, setSummary] = useState<ProposalSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [activeTab, setActiveTab] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [data, sum] = await Promise.all([
        api.getProposals(projectId, activeTab || undefined),
        api.getProposalSummary(projectId),
      ]);
      setProposals(data);
      setSummary(sum);
    } catch { /* silent */ }
    setLoading(false);
  }, [projectId, activeTab]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  async function handleAnalyze() {
    setAnalyzing(true);
    try {
      await api.analyzeProject(projectId);
      setActiveTab("draft");
      await fetchData();
    } catch { /* silent */ }
    setAnalyzing(false);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">
          R&D Lab
        </h3>
        <button
          onClick={handleAnalyze}
          disabled={analyzing}
          className="text-xs px-3 py-1.5 rounded-lg bg-purple-600 text-white font-medium hover:bg-purple-500 transition-colors disabled:opacity-40"
        >
          {analyzing ? "Analyzing..." : "Analyze Project"}
        </button>
      </div>

      {/* Summary */}
      {summary && summary.total > 0 && (
        <div className="flex gap-3 text-xs text-zinc-500">
          <span>{summary.counts.draft || 0} drafts</span>
          <span>{summary.counts.under_review || 0} in review</span>
          <span>{summary.counts.approved || 0} approved</span>
          <span>{summary.counts.converted_to_goal || 0} converted</span>
        </div>
      )}

      {/* Tabs */}
      {summary && summary.total > 0 && (
        <div className="flex gap-1">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                activeTab === tab.key
                  ? "bg-zinc-700 text-zinc-200"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {loading && <p className="text-xs text-zinc-500">Loading proposals...</p>}

      {!loading && proposals.length === 0 && (
        <p className="text-xs text-zinc-600">
          No proposals yet. Click &quot;Analyze Project&quot; to scan for improvement opportunities.
        </p>
      )}

      <div className="space-y-2">
        {proposals.map((p) => (
          <ProposalCard key={p.id} proposal={p} onAction={fetchData} />
        ))}
      </div>
    </div>
  );
}
