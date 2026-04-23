"use client";

import type { BrainstormAgent, BrainstormSkill, BrainstormSynthesis } from "@/lib/types";

type Props = {
  agents: BrainstormAgent[];
  skills: BrainstormSkill[];
  status: string;
  currentRound: number;
  maxRounds: number;
  mode: string;
  synthesis: BrainstormSynthesis | null;
  onAdvance: () => void;
  onSkip: () => void;
  onSpawn: () => void;
  onModeChange: (mode: string) => void;
  onSkillUpdate: (skillId: string, status: string) => void;
};

const MODE_OPTIONS = [
  { value: "normal", label: "Normal", desc: "Balanced discussion" },
  { value: "deep_dive", label: "Deep Dive", desc: "Explore one topic deeply" },
  { value: "exploration", label: "Exploration", desc: "Generate alternatives" },
  { value: "decision", label: "Decision", desc: "Converge on final plan" },
];

export default function ControlCenter({
  agents,
  skills,
  status,
  currentRound,
  maxRounds,
  mode,
  synthesis,
  onAdvance,
  onSkip,
  onSpawn,
  onModeChange,
  onSkillUpdate,
}: Props) {
  const isBrainstorming = status === "brainstorming";
  const isReadyToSpawn = status === "ready_to_spawn";
  const isSpawned = status === "spawned";
  const pastSoftLimit = currentRound >= maxRounds;

  return (
    <div className="space-y-4 overflow-y-auto">
      {/* Status & Mode */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Mode
        </h3>
        <div className="grid grid-cols-2 gap-1.5">
          {MODE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => onModeChange(opt.value)}
              disabled={!isBrainstorming}
              className={`text-left px-2.5 py-2 rounded-lg border text-[10px] transition-colors disabled:opacity-40 ${
                mode === opt.value
                  ? "bg-info/10 border-info/30 text-info"
                  : "bg-base-50 border-border text-zinc-400 hover:border-zinc-600"
              }`}
            >
              <span className="font-medium block">{opt.label}</span>
              <span className="text-zinc-600">{opt.desc}</span>
            </button>
          ))}
        </div>
        <div className="mt-2 flex items-center justify-between text-xs px-1">
          <span className="text-zinc-400 capitalize">{status.replace("_", " ")}</span>
          <span className="text-zinc-500">
            Round {currentRound}{pastSoftLimit ? " (past limit)" : `/${maxRounds}`}
          </span>
        </div>
      </div>

      {/* Synthesis Banner */}
      {synthesis && (
        <div className="bg-info/5 border border-info/20 rounded-lg p-3">
          <p className="text-xs text-info font-medium mb-1">Synthesis</p>
          <p className="text-[11px] text-zinc-400">{synthesis.summary_text}</p>
        </div>
      )}

      {/* Dynamic Summary */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Summary
        </h3>
        <div className="bg-base-50 border border-border rounded-lg p-3 space-y-2">
          {synthesis ? (
            <>
              {synthesis.key_decisions.length > 0 && (
                <div>
                  <p className="text-[10px] text-healthy font-medium">Decisions ({synthesis.key_decisions.length})</p>
                  {synthesis.key_decisions.slice(0, 3).map((d, i) => (
                    <p key={i} className="text-[10px] text-zinc-500 truncate">• {d}</p>
                  ))}
                </div>
              )}
              {synthesis.risks_identified.length > 0 && (
                <div>
                  <p className="text-[10px] text-error font-medium">Risks ({synthesis.risks_identified.length})</p>
                  {synthesis.risks_identified.slice(0, 2).map((r, i) => (
                    <p key={i} className="text-[10px] text-zinc-500 truncate">• {r}</p>
                  ))}
                </div>
              )}
              {synthesis.open_questions.length > 0 && (
                <div>
                  <p className="text-[10px] text-amber-400 font-medium">Open Questions ({synthesis.open_questions.length})</p>
                  {synthesis.open_questions.slice(0, 2).map((q, i) => (
                    <p key={i} className="text-[10px] text-zinc-500 truncate">• {q}</p>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="text-[10px] text-zinc-600">Advancing rounds will generate a synthesis</p>
          )}
        </div>
      </div>

      {/* Skills */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Skills ({skills.filter(s => s.status === "accepted").length}/{skills.length})
        </h3>
        <div className="space-y-1">
          {skills.map((skill) => (
            <div key={skill.id} className="flex items-center gap-1.5 bg-base-50 border border-border rounded px-2.5 py-1.5">
              <span className="text-[10px] text-zinc-300 flex-1 truncate">{skill.skill_name}</span>
              {skill.status === "suggested" && (
                <>
                  <button onClick={() => onSkillUpdate(skill.id, "accepted")} className="text-[9px] px-1.5 py-0.5 rounded bg-healthy/10 text-healthy hover:bg-healthy/20">✓</button>
                  <button onClick={() => onSkillUpdate(skill.id, "rejected")} className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-400 hover:bg-zinc-600">✗</button>
                </>
              )}
              {skill.status === "accepted" && <span className="text-[9px] text-healthy">✓</span>}
              {skill.status === "rejected" && <span className="text-[9px] text-zinc-600">✗</span>}
            </div>
          ))}
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
                Continue Brainstorm {pastSoftLimit ? "(past limit)" : `(${currentRound}/${maxRounds})`}
              </button>
              <button
                onClick={() => onModeChange("deep_dive")}
                className="w-full px-3 py-2 rounded-lg bg-purple-400/10 text-purple-400 text-xs font-medium hover:bg-purple-400/20 transition-colors"
              >
                Deep Dive This Topic
              </button>
              <button
                onClick={() => onModeChange("exploration")}
                className="w-full px-3 py-2 rounded-lg bg-cyan-400/10 text-cyan-400 text-xs font-medium hover:bg-cyan-400/20 transition-colors"
              >
                Generate Alternatives
              </button>
              <button
                onClick={onSkip}
                className="w-full px-3 py-2 rounded-lg bg-zinc-800 text-zinc-400 text-xs font-medium hover:bg-zinc-700 transition-colors"
              >
                Finalize & Spawn Project
              </button>
            </>
          )}
          {(isReadyToSpawn || status === "refining") && !isSpawned && (
            <button
              onClick={onSpawn}
              className="w-full px-3 py-2.5 rounded-lg bg-healthy text-white text-sm font-medium hover:bg-healthy/90 transition-colors"
            >
              Confirm & Spawn Project
            </button>
          )}
          {isSpawned && (
            <p className="text-xs text-zinc-500 text-center py-2">Project spawned</p>
          )}
        </div>
      </div>
    </div>
  );
}
