"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Project, BrainstormRoom } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  brainstorming: "bg-info/10 text-info",
  refining: "bg-amber-500/10 text-amber-400",
  ready_to_spawn: "bg-healthy/10 text-healthy",
  spawned: "bg-zinc-700/50 text-zinc-500",
};

const STATUS_LABELS: Record<string, string> = {
  brainstorming: "Brainstorming",
  refining: "Refining",
  ready_to_spawn: "Ready to Spawn",
  spawned: "Spawned",
};

export default function GlobalLobby() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [brainstormRooms, setBrainstormRooms] = useState<BrainstormRoom[]>([]);
  const [newIdea, setNewIdea] = useState("");
  const [showNewIdea, setShowNewIdea] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const [projs, rooms] = await Promise.all([
        api.getProjects(),
        api.getBrainstormRooms(),
      ]);
      setProjects(projs);
      setBrainstormRooms(rooms);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  async function handleCreateIdea() {
    if (!newIdea.trim()) return;
    try {
      const room = await api.createBrainstormRoom({ idea_text: newIdea.trim() });
      router.push(`/brainstorm/${room.id}`);
    } catch {}
  }

  async function handleCreateProject() {
    const name = prompt("Project name:");
    if (!name) return;
    try {
      const project = await api.createProject({ name, description: "" });
      router.push(`/project/${project.id}`);
    } catch {}
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 border-2 border-info border-t-transparent rounded-full animate-spin" />
          <span className="text-zinc-400">Loading...</span>
        </div>
      </div>
    );
  }

  const activeRooms = brainstormRooms.filter((r) => r.status !== "spawned");
  const spawnedRooms = brainstormRooms.filter((r) => r.status === "spawned");

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-border px-4 sm:px-6 py-6">
        <div className="max-w-[1200px] mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">ORKA</h1>
            <p className="text-sm text-zinc-500 mt-1">AI Command Center</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowNewIdea(!showNewIdea)}
              className="px-4 py-2 rounded-lg bg-info text-white text-sm font-medium hover:bg-info/90 transition-colors"
            >
              New Idea
            </button>
            <button
              onClick={handleCreateProject}
              className="px-4 py-2 rounded-lg bg-zinc-800 text-zinc-300 text-sm font-medium hover:bg-zinc-700 transition-colors"
            >
              New Project
            </button>
          </div>
        </div>
      </header>

      {/* New Idea Input */}
      {showNewIdea && (
        <div className="border-b border-border px-4 sm:px-6 py-4">
          <div className="max-w-[1200px] mx-auto">
            <div className="flex gap-3">
              <input
                type="text"
                value={newIdea}
                onChange={(e) => setNewIdea(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreateIdea()}
                placeholder="Describe your idea... (agents will brainstorm it)"
                className="flex-1 bg-base-50 border border-border rounded-lg px-4 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-info/50"
                autoFocus
              />
              <button
                onClick={handleCreateIdea}
                disabled={!newIdea.trim()}
                className="px-6 py-2.5 rounded-lg bg-info text-white text-sm font-medium hover:bg-info/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Start Brainstorm
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="max-w-[1200px] mx-auto px-4 sm:px-6 py-8 space-y-10">
        {/* Active Brainstorm Rooms */}
        <section>
          <h2 className="text-sm font-medium text-zinc-400 mb-4 uppercase tracking-wider">
            Brainstorm Rooms ({activeRooms.length})
          </h2>
          {activeRooms.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-border rounded-lg">
              <p className="text-zinc-500 text-sm">No active brainstorm rooms</p>
              <p className="text-zinc-600 text-xs mt-1">Click &quot;New Idea&quot; to start one</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {activeRooms.map((room) => (
                <button
                  key={room.id}
                  onClick={() => router.push(`/brainstorm/${room.id}`)}
                  className="text-left bg-base-50 border border-border rounded-lg p-4 hover:border-info/30 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <h3 className="text-sm font-medium truncate flex-1">
                      {room.title}
                    </h3>
                    <span className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-medium ${STATUS_STYLES[room.status]}`}>
                      {STATUS_LABELS[room.status]}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-500 line-clamp-2 mb-2">
                    {room.idea_text}
                  </p>
                  <div className="flex items-center gap-3 text-[10px] text-zinc-600">
                    <span>Round {room.current_round}/{room.max_rounds}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Project Rooms */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">
              Project Rooms ({projects.length})
            </h2>
          </div>
          {projects.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-border rounded-lg">
              <p className="text-zinc-500 text-sm">No projects yet</p>
              <p className="text-zinc-600 text-xs mt-1">Spawn from a brainstorm or create directly</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {projects.map((project) => {
                const spawnedFrom = spawnedRooms.find(
                  (r) => r.project_id === project.id
                );
                return (
                  <button
                    key={project.id}
                    onClick={() => router.push(`/project/${project.id}`)}
                    className="text-left bg-base-50 border border-border rounded-lg p-4 hover:border-healthy/30 transition-colors"
                  >
                    <h3 className="text-sm font-medium truncate">
                      {project.name}
                    </h3>
                    {project.description && (
                      <p className="text-xs text-zinc-500 line-clamp-2 mt-1">
                        {project.description}
                      </p>
                    )}
                    {spawnedFrom && (
                      <span className="inline-block mt-2 px-2 py-0.5 rounded text-[10px] font-medium bg-info/10 text-info">
                        From brainstorm
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
