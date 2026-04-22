"use client";

import { useState } from "react";
import type { Project } from "@/lib/types";

interface ProjectSelectorProps {
  projects: Project[];
  onSelect: (id: string) => void;
  onCreate: (data: { name: string; description: string }) => void;
}

export default function ProjectSelector({
  projects,
  onSelect,
  onCreate,
}: ProjectSelectorProps) {
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      await onCreate({ name: name.trim(), description: description.trim() });
      setName("");
      setDescription("");
      setShowForm(false);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-medium">Projects</h2>
          <p className="text-sm text-zinc-500 mt-1">
            Select a project to view its dashboard
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 rounded-lg bg-info/10 text-info text-sm font-medium hover:bg-info/20 transition-colors"
        >
          {showForm ? "Cancel" : "+ New Project"}
        </button>
      </div>

      {/* New Project Form */}
      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 bg-base-50 border border-border rounded-lg p-4"
        >
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-zinc-400 mb-1 font-medium">
                Project Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My Project"
                className="w-full bg-base border border-border rounded-md px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:border-info focus:ring-0 outline-none transition-colors"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-400 mb-1 font-medium">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What is this project about?"
                rows={2}
                className="w-full bg-base border border-border rounded-md px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:border-info focus:ring-0 outline-none transition-colors resize-none"
              />
            </div>
            <button
              type="submit"
              disabled={creating || !name.trim()}
              className="px-4 py-2 rounded-md bg-info text-white text-sm font-medium hover:bg-info/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {creating ? "Creating..." : "Create Project"}
            </button>
          </div>
        </form>
      )}

      {/* Project List */}
      {projects.length === 0 && !showForm ? (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <div className="w-16 h-16 rounded-2xl bg-base-50 border border-border flex items-center justify-center">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-zinc-600"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
          </div>
          <div className="text-center">
            <p className="text-zinc-400 text-sm">
              Create your first project to get started
            </p>
            <button
              onClick={() => setShowForm(true)}
              className="mt-3 text-sm text-info hover:text-info/80 transition-colors"
            >
              + New Project
            </button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {projects.map((project) => (
            <button
              key={project.id}
              onClick={() => onSelect(project.id)}
              className="text-left bg-base-50 border border-border rounded-lg p-4 hover:border-border-light hover:bg-base-100 transition-all group"
            >
              <h3 className="font-medium text-sm group-hover:text-info transition-colors">
                {project.name}
              </h3>
              {project.description && (
                <p className="text-xs text-zinc-500 mt-1 line-clamp-2">
                  {project.description}
                </p>
              )}
              <p className="text-[11px] text-zinc-600 mt-2">
                Created {formatDate(project.created_at)}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function formatDate(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}
