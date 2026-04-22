import type { Project, Task, Agent, ActivityLog, MemorySnapshot, Summary } from "./types";

const API_BASE = "http://localhost:8000";

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };

  const res = await fetch(url, {
    ...options,
    headers: {
      ...headers,
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API Error ${res.status}: ${text}`);
  }

  return res.json() as Promise<T>;
}

export const api = {
  // Projects
  getProjects: () => fetchJSON<Project[]>(`${API_BASE}/api/projects`),

  createProject: (data: { name: string; description: string }) =>
    fetchJSON<Project>(`${API_BASE}/api/projects`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getProject: (id: string) => fetchJSON<Project>(`${API_BASE}/api/projects/${id}`),

  // Tasks
  getTasks: (projectId: string) =>
    fetchJSON<Task[]>(`${API_BASE}/api/tasks?project_id=${projectId}`),

  createTask: (data: { project_id: string; content: string }) =>
    fetchJSON<Task>(`${API_BASE}/api/tasks`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  distributeTask: (taskId: string) =>
    fetchJSON<Task>(`${API_BASE}/api/tasks/${taskId}/distribute`, {
      method: "POST",
    }),

  completeTask: (taskId: string) =>
    fetchJSON<Task>(`${API_BASE}/api/tasks/${taskId}/complete`, {
      method: "POST",
    }),

  // Agents
  getAgents: () => fetchJSON<Agent[]>(`${API_BASE}/api/agents`),

  // Activity
  getActivity: (projectId: string) =>
    fetchJSON<ActivityLog[]>(`${API_BASE}/api/activity?project_id=${projectId}`),

  // Memory
  getMemory: (projectId: string) =>
    fetchJSON<MemorySnapshot>(`${API_BASE}/api/memory/${projectId}`),

  // Summary
  getSummary: (projectId: string) =>
    fetchJSON<Summary>(`${API_BASE}/api/summary/${projectId}`),
};
