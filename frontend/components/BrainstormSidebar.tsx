"use client";

import type { BrainstormAgent, BrainstormSkill } from "@/lib/types";

type Props = {
  agents: BrainstormAgent[];
  skills: BrainstormSkill[];
  status: string;
  currentRound: number;
  maxRounds: number;
  onAdvance: () => void;
  onSkip: () => void;
  onSpawn: () => void;
  onSkillUpdate: (skillId: string, status: string) => void;
};

const AGENT_COLORS: Record<string, string> = {
  orchestrator: "bg-info",
  backend: "bg-healthy",
  frontend: "bg-purple-400",
  qa: "bg-error",
  docs: "bg-amber-400",
  memory: "bg-cyan-400",
};

export default function BrainstormSidebar({
  agents,
  skills,
  status,
  currentRound,
  maxRounds,
  onAdvance,
  onSkip,
  onSpawn,
  onSkillUpdate,
}: Props) {
  const isBrainstorming = status === "brainstorming";
  const isReadyToSpawn = status === "ready_to_spawn";
  const isSpawned = status === "spawned";

  return (
    <div className="space-y-5">
      {/* Round Status */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Status
        </h3>
        <div className="bg-base-50 border border-border rounded-lg p-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-zinc-300 capitalize">{status.replace("_", " ")}</span>
            <span className="text-xs text-zinc-500">
              Round {currentRound}/{maxRounds}
            </span>
          </div>
          <div className="mt-2 w-full bg-zinc-800 rounded-full h-1.5">
            <div
              className="bg-info rounded-full h-1.5 transition-all"
              style={{ width: `${(currentRound / maxRounds) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Agents */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Agents
        </h3>
        <div className="space-y-1.5">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="flex items-center gap-2 bg-base-50 border border-border rounded px-3 py-2"
            >
              <span className={`w-2 h-2 rounded-full ${AGENT_COLORS[agent.agent_type] || "bg-zinc-500"}`} />
              <span className="text-xs text-zinc-300 flex-1 truncate">
                {agent.agent_name}
              </span>
              <span className="text-[10px] text-zinc-600 capitalize">{agent.status}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Skills */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Suggested Skills
        </h3>
        <div className="space-y-1.5">
          {skills.map((skill) => (
            <div
              key={skill.id}
              className="bg-base-50 border border-border rounded px-3 py-2"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-zinc-300 font-medium">{skill.skill_name}</span>
                <div className="flex gap-1">
                  {skill.status !== "accepted" && (
                    <button
                      onClick={() => onSkillUpdate(skill.id, "accepted")}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-healthy/10 text-healthy hover:bg-healthy/20"
                    >
                      Accept
                    </button>
                  )}
                  {skill.status !== "rejected" && (
                    <button
                      onClick={() => onSkillUpdate(skill.id, "rejected")}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-400 hover:bg-zinc-600"
                    >
                      Reject
                    </button>
                  )}
                </div>
              </div>
              <p className="text-[10px] text-zinc-500">{skill.relevance_reason}</p>
            </div>
          ))}
          {skills.length === 0 && (
            <p className="text-xs text-zinc-500">Skills detected from your idea</p>
          )}
        </div>
      </div>

      {/* Actions */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Actions
        </h3>
        <div className="space-y-2">
          {isBrainstorming && (
            <>
              <button
                onClick={onAdvance}
                className="w-full px-3 py-2 rounded-lg bg-info/10 text-info text-xs font-medium hover:bg-info/20 transition-colors"
              >
                Advance Round ({currentRound}/{maxRounds})
              </button>
              <button
                onClick={onSkip}
                className="w-full px-3 py-2 rounded-lg bg-zinc-800 text-zinc-400 text-xs font-medium hover:bg-zinc-700 transition-colors"
              >
                Skip to Plan
              </button>
            </>
          )}
          {(isReadyToSpawn || status === "refining") && !isSpawned && (
            <button
              onClick={onSpawn}
              className="w-full px-3 py-2.5 rounded-lg bg-healthy text-white text-sm font-medium hover:bg-healthy/90 transition-colors"
            >
              Finalize & Spawn Project
            </button>
          )}
          {isSpawned && (
            <p className="text-xs text-zinc-500 text-center py-2">
              Project spawned
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
