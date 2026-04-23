"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { BrainstormRoomDetail, BrainstormSynthesis, BrainstormMessage } from "@/lib/types";
import AgentCard from "@/components/AgentCard";
import MeetingRoom from "@/components/MeetingRoom";
import ControlCenter from "@/components/ControlCenter";

const STATUS_STYLES: Record<string, string> = {
  brainstorming: "bg-info/10 text-info",
  refining: "bg-amber-500/10 text-amber-400",
  ready_to_spawn: "bg-healthy/10 text-healthy",
  spawned: "bg-zinc-700/50 text-zinc-500",
};

const STATUS_LABELS: Record<string, string> = {
  brainstorming: "Brainstorming",
  refining: "Refining Plan",
  ready_to_spawn: "Ready to Spawn",
  spawned: "Spawned",
};

const MODE_LABELS: Record<string, string> = {
  normal: "Normal",
  deep_dive: "Deep Dive",
  exploration: "Exploration",
  decision: "Decision",
};

export default function BrainstormRoomPage() {
  const params = useParams();
  const router = useRouter();
  const roomId = params.id as string;

  const [room, setRoom] = useState<BrainstormRoomDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [spawning, setSpawning] = useState(false);

  const loadRoom = useCallback(async () => {
    try {
      const data = await api.getBrainstormRoom(roomId);
      setRoom(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load room");
    }
  }, [roomId]);

  useEffect(() => {
    loadRoom().then(() => setLoading(false));
  }, [loadRoom]);

  useEffect(() => {
    if (room?.status === "brainstorming") {
      const interval = setInterval(loadRoom, 5000);
      return () => clearInterval(interval);
    }
  }, [room?.status, loadRoom]);

  const synthesis: BrainstormSynthesis | null = useMemo(() => {
    if (!room?.synthesis) return null;
    try { return JSON.parse(room.synthesis); } catch { return null; }
  }, [room?.synthesis]);

  // Map agent_id -> latest message type for agent cards
  const agentLatestMsg = useMemo(() => {
    const map: Record<string, string> = {};
    if (!room) return map;
    for (const msg of [...room.messages].reverse()) {
      if (msg.agent_id && !map[msg.agent_id]) {
        map[msg.agent_id] = msg.message_type;
      }
    }
    return map;
  }, [room?.messages]);

  async function handleAdvance() {
    try {
      await api.advanceBrainstormRoom(roomId);
      await loadRoom();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to advance");
    }
  }

  async function handleSendMessage(content: string, targetAgentType?: string) {
    try {
      await api.sendBrainstormMessage(roomId, content, targetAgentType);
      await loadRoom();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    }
  }

  async function handleSkip() {
    try {
      await api.skipBrainstormRoom(roomId);
      await loadRoom();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to skip");
    }
  }

  async function handleSpawn() {
    setSpawning(true);
    try {
      const result = await api.spawnBrainstormRoom(roomId);
      router.push(`/project/${result.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to spawn");
      setSpawning(false);
    }
  }

  async function handleModeChange(mode: string) {
    try {
      await api.setBrainstormMode(roomId, mode);
      await loadRoom();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change mode");
    }
  }

  async function handleSkillUpdate(skillId: string, status: string) {
    try {
      await api.updateBrainstormSkill(roomId, skillId, status);
      await loadRoom();
    } catch {}
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 border-2 border-info border-t-transparent rounded-full animate-spin" />
          <span className="text-zinc-400">Loading room...</span>
        </div>
      </div>
    );
  }

  if (error && !room) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-zinc-400 text-sm">{error}</p>
        <button onClick={() => router.push("/")} className="text-sm text-info hover:text-info/80">Back to Lobby</button>
      </div>
    );
  }

  if (!room) return null;

  return (
    <div className="min-h-screen flex flex-col bg-zinc-950">
      {/* Header */}
      <header className="border-b border-border px-4 sm:px-6 py-3 bg-zinc-900/80">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/")}
              className="text-zinc-500 hover:text-zinc-300 transition-colors text-sm flex items-center gap-1"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6" /></svg>
              Lobby
            </button>
            <div className="w-px h-5 bg-border" />
            <h1 className="text-base font-semibold truncate max-w-[200px] sm:max-w-[400px]">{room.title}</h1>
            <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${STATUS_STYLES[room.status]}`}>
              {STATUS_LABELS[room.status]}
            </span>
            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-zinc-800 text-zinc-400">
              {MODE_LABELS[room.mode] || room.mode}
            </span>
          </div>
          {error && <span className="text-xs text-error hidden sm:inline">{error}</span>}
        </div>
      </header>

      {/* Main 3-column layout */}
      <main className="flex-1 px-4 sm:px-6 py-4 overflow-hidden">
        <div className="max-w-[1600px] mx-auto grid grid-cols-1 lg:grid-cols-[200px_1fr_280px] gap-4 h-full" style={{ minHeight: "calc(100vh - 120px)" }}>

          {/* LEFT: Team Panel */}
          <div className="space-y-2 overflow-y-auto">
            <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2 sticky top-0 bg-zinc-950 py-1">
              Team
            </h3>
            {room.agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                latestMessageType={agentLatestMsg[agent.id] || null}
              />
            ))}
          </div>

          {/* CENTER: Meeting Room */}
          <div className="min-h-[400px]">
            <MeetingRoom
              messages={room.messages}
              onSendMessage={handleSendMessage}
              disabled={room.status !== "brainstorming" || spawning}
            />
          </div>

          {/* RIGHT: Control Center */}
          <div>
            <ControlCenter
              agents={room.agents}
              skills={room.skills}
              status={room.status}
              currentRound={room.current_round}
              maxRounds={room.max_rounds}
              mode={room.mode}
              synthesis={synthesis}
              onAdvance={handleAdvance}
              onSkip={handleSkip}
              onSpawn={handleSpawn}
              onModeChange={handleModeChange}
              onSkillUpdate={handleSkillUpdate}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
