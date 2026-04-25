"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { ImprovementProposal, ApprovalGuard } from "@/lib/types";

interface ProposalCardProps {
  proposal: ImprovementProposal;
  onAction: () => void;
}

const STATUS_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  draft: { label: "Draft", color: "text-zinc-400", bg: "bg-zinc-800" },
  under_review: { label: "Under Review", color: "text-blue-400", bg: "bg-blue-400/10" },
  approved: { label: "Approved", color: "text-emerald-400", bg: "bg-emerald-400/10" },
  rejected: { label: "Rejected", color: "text-red-400", bg: "bg-red-400/10" },
  converted_to_goal: { label: "Converted", color: "text-purple-400", bg: "bg-purple-400/10" },
  archived: { label: "Archived", color: "text-zinc-600", bg: "bg-zinc-900" },
};

const RISK_STYLES: Record<string, string> = {
  low: "text-green-400",
  medium: "text-yellow-400",
  high: "text-orange-400",
  critical: "text-red-400",
};

export default function ProposalCard({ proposal, onAction }: ProposalCardProps) {
  const [guard, setGuard] = useState<ApprovalGuard | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [confirmApprove, setConfirmApprove] = useState(false);

  const style = STATUS_STYLES[proposal.status] || STATUS_STYLES.draft;
  const riskColor = RISK_STYLES[proposal.risk_level] || "text-zinc-500";

  async function handleLoadGuard() {
    setLoading(true);
    try {
      const g = await api.getProposalGuard(proposal.id);
      setGuard(g);
    } catch { /* silent */ }
    setLoading(false);
  }

  async function handleSubmit() {
    setLoading(true);
    try { await api.submitProposal(proposal.id); onAction(); }
    catch { /* silent */ }
    setLoading(false);
  }

  async function handleApprove() {
    setLoading(true);
    try {
      await api.approveProposal(proposal.id, true);
      setConfirmApprove(false);
      onAction();
    } catch { /* silent */ }
    setLoading(false);
  }

  async function handleConvert() {
    setLoading(true);
    try { await api.convertProposal(proposal.id); onAction(); }
    catch { /* silent */ }
    setLoading(false);
  }

  async function handleReject() {
    setLoading(true);
    try { await api.rejectProposal(proposal.id); onAction(); }
    catch { /* silent */ }
    setLoading(false);
  }

  async function handleArchive() {
    setLoading(true);
    try { await api.archiveProposal(proposal.id); onAction(); }
    catch { /* silent */ }
    setLoading(false);
  }

  const relatedRuns = JSON.parse(proposal.related_run_ids || "[]") as string[];

  return (
    <div className="rounded-lg border border-border bg-base-50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2.5 flex items-center gap-3 text-left hover:bg-base-100 transition-colors"
      >
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${style.color} ${style.bg}`}>
          {style.label}
        </span>
        <span className={`text-xs font-medium ${riskColor}`}>
          {proposal.risk_level}
        </span>
        <span className="flex-1 text-sm text-zinc-300 truncate">{proposal.title}</span>
        <span className="text-xs text-zinc-600">{proposal.analysis_type}</span>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-3 border-t border-border">
          {/* Problem */}
          <div className="pt-2">
            <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">Problem</p>
            <p className="text-sm text-zinc-300">{proposal.problem_description}</p>
          </div>

          {/* Solution */}
          <div>
            <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">Suggested Solution</p>
            <p className="text-sm text-zinc-300">{proposal.suggested_solution}</p>
          </div>

          {/* Impact */}
          {proposal.expected_impact && (
            <div>
              <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">Expected Impact</p>
              <p className="text-sm text-zinc-400">{proposal.expected_impact}</p>
            </div>
          )}

          {/* Evidence links */}
          {relatedRuns.length > 0 && (
            <div>
              <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">
                Evidence ({relatedRuns.length} runs)
              </p>
              <div className="flex flex-wrap gap-1">
                {relatedRuns.slice(0, 5).map((rid) => (
                  <span key={rid} className="text-xs font-mono text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded">
                    {rid.slice(0, 8)}...
                  </span>
                ))}
                {relatedRuns.length > 5 && (
                  <span className="text-xs text-zinc-600">+{relatedRuns.length - 5} more</span>
                )}
              </div>
            </div>
          )}

          {/* Guard */}
          {guard && (
            <div className="rounded-md border border-border bg-base-100 p-2 space-y-1">
              <p className="text-xs text-zinc-500 uppercase tracking-wider">Safety Guard</p>
              <div className="grid grid-cols-2 gap-1 text-xs">
                <span className="text-zinc-500">Est. runs:</span>
                <span className="text-zinc-300">{guard.estimated_runs}</span>
                <span className="text-zinc-500">Est. cost:</span>
                <span className="text-zinc-300">${guard.estimated_cost_usd.toFixed(2)}</span>
                <span className="text-zinc-500">Budget fits:</span>
                <span className={guard.budget_fits ? "text-emerald-400" : "text-red-400"}>
                  {guard.budget_fits ? "Yes" : "No"}
                </span>
                <span className="text-zinc-500">Can proceed:</span>
                <span className={guard.can_proceed ? "text-emerald-400" : "text-red-400"}>
                  {guard.can_proceed ? "Yes" : "No"}
                </span>
              </div>
              {guard.warnings.length > 0 && (
                <div className="mt-1">
                  {guard.warnings.map((w, i) => (
                    <p key={i} className="text-xs text-yellow-500">Warning: {w}</p>
                  ))}
                </div>
              )}
              {guard.blocks.length > 0 && (
                <div className="mt-1">
                  {guard.blocks.map((b, i) => (
                    <p key={i} className="text-xs text-red-400">Blocked: {b}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-wrap gap-2 pt-1">
            {proposal.status === "draft" && (
              <>
                <button onClick={handleSubmit} disabled={loading}
                  className="text-xs px-2.5 py-1 rounded bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 transition-colors disabled:opacity-40">
                  Submit for Review
                </button>
                <button onClick={handleArchive} disabled={loading}
                  className="text-xs px-2.5 py-1 rounded bg-zinc-700/30 text-zinc-500 hover:bg-zinc-700/50 transition-colors disabled:opacity-40">
                  Archive
                </button>
              </>
            )}
            {proposal.status === "under_review" && (
              <>
                {!guard && (
                  <button onClick={handleLoadGuard} disabled={loading}
                    className="text-xs px-2.5 py-1 rounded bg-yellow-600/20 text-yellow-400 hover:bg-yellow-600/30 transition-colors disabled:opacity-40">
                    {loading ? "Loading..." : "Run Safety Guard"}
                  </button>
                )}
                {guard && !confirmApprove && guard.can_proceed && (
                  <button onClick={() => setConfirmApprove(true)}
                    className="text-xs px-2.5 py-1 rounded bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/30 transition-colors">
                    Approve
                  </button>
                )}
                {confirmApprove && (
                  <button onClick={handleApprove} disabled={loading}
                    className="text-xs px-2.5 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-40">
                    Confirm Approval
                  </button>
                )}
                <button onClick={handleReject} disabled={loading}
                  className="text-xs px-2.5 py-1 rounded bg-red-600/20 text-red-400 hover:bg-red-600/30 transition-colors disabled:opacity-40">
                  Reject
                </button>
              </>
            )}
            {proposal.status === "approved" && (
              <button onClick={handleConvert} disabled={loading}
                className="text-xs px-2.5 py-1 rounded bg-purple-600/20 text-purple-400 hover:bg-purple-600/30 transition-colors disabled:opacity-40">
                Convert to Goal
              </button>
            )}
            {proposal.status === "converted_to_goal" && proposal.implementation_goal_id && (
              <span className="text-xs text-purple-400 font-mono">
                Goal: {proposal.implementation_goal_id.slice(0, 8)}...
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
