"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import ProjectSelector from "@/components/ProjectSelector";

export default function HomePage() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadProjects();
  }, []);

  async function loadProjects() {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getProjects();
      setProjects(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load projects");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(data: { name: string; description: string }) {
    try {
      const project = await api.createProject(data);
      setProjects((prev) => [...prev, project]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create project");
    }
  }

  function handleSelect(id: string) {
    router.push(`/project/${id}`);
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-info/20 flex items-center justify-center">
              <span className="text-info font-bold text-sm">O</span>
            </div>
            <h1 className="text-xl font-semibold tracking-tight">ORKA</h1>
            <span className="text-xs text-zinc-500 hidden sm:inline">
              AI Command Center
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-healthy animate-pulse" />
            <span className="text-xs text-zinc-500">System Online</span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 px-6 py-8">
        <div className="max-w-7xl mx-auto">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <div className="flex items-center gap-3">
                <div className="w-5 h-5 border-2 border-info border-t-transparent rounded-full animate-spin" />
                <span className="text-zinc-400">Loading projects...</span>
              </div>
            </div>
          ) : error && projects.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <div className="w-12 h-12 rounded-full bg-error/10 flex items-center justify-center">
                <span className="text-error text-xl">!</span>
              </div>
              <p className="text-zinc-400 text-sm">{error}</p>
              <button
                onClick={loadProjects}
                className="text-sm text-info hover:text-info/80 transition-colors"
              >
                Retry
              </button>
            </div>
          ) : (
            <ProjectSelector
              projects={projects}
              onSelect={handleSelect}
              onCreate={handleCreate}
            />
          )}
        </div>
      </main>
    </div>
  );
}
