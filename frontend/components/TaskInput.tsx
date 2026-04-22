"use client";

import { useState } from "react";
import { api } from "@/lib/api";

interface TaskInputProps {
  projectId: string;
  onSubmit: () => void;
}

export default function TaskInput({ projectId, onSubmit }: TaskInputProps) {
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim() || submitting) return;

    setSubmitting(true);
    setError(null);

    try {
      const task = await api.createTask({
        project_id: projectId,
        content: content.trim(),
      });
      setContent("");

      // Attempt to distribute the task to the orchestrator
      try {
        await api.distributeTask(task.id);
      } catch {
        // Distribution failure is non-critical; task still exists
      }

      onSubmit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit task");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-2">
      <div className="flex-1">
        <input
          type="text"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Describe a task for the team..."
          disabled={submitting}
          className="w-full bg-base border border-border rounded-lg px-4 py-2.5 text-sm text-zinc-200 placeholder-zinc-600 focus:border-info focus:ring-0 outline-none transition-colors disabled:opacity-50"
        />
      </div>
      <button
        type="submit"
        disabled={submitting || !content.trim()}
        className="px-5 py-2.5 rounded-lg bg-info text-white text-sm font-medium hover:bg-info/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
      >
        {submitting ? (
          <span className="flex items-center gap-2">
            <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            Submitting
          </span>
        ) : (
          "Submit Task"
        )}
      </button>
      {error && (
        <p className="text-xs text-error sm:absolute sm:mt-1">{error}</p>
      )}
    </form>
  );
}
