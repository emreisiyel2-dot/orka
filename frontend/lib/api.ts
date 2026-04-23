import type { Project, Task, Agent, ActivityLog, MemorySnapshot, Summary, Worker, WorkerSession, WorkerSessionDetail, WorkerLog, AutonomousDecision, HealthStatus, WorkerHealthDetail, AgentMessage, TaskDependency } from "./types";

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

  // Workers
  getWorkers: () => fetchJSON<Worker[]>(`${API_BASE}/api/workers`),

  // Sessions
  getSessions: (projectId?: string) =>
    fetchJSON<WorkerSession[]>(`${API_BASE}/api/sessions${projectId ? `?project_id=${projectId}` : ''}`),

  getSessionDetail: (sessionId: string) =>
    fetchJSON<WorkerSessionDetail>(`${API_BASE}/api/sessions/${sessionId}`),

  sendSessionInput: (sessionId: string, input_value: string) =>
    fetchJSON<WorkerSession>(`${API_BASE}/api/sessions/${sessionId}/input`, {
      method: 'POST',
      body: JSON.stringify({ input_value }),
    }),

  getSessionLogs: (sessionId: string) =>
    fetchJSON<WorkerLog[]>(`${API_BASE}/api/sessions/${sessionId}/logs`),

  getSessionDecisions: (sessionId: string) =>
    fetchJSON<AutonomousDecision[]>(`${API_BASE}/api/sessions/${sessionId}/decisions`),

  // Health
  getHealth: () => fetchJSON<HealthStatus>(`${API_BASE}/health`),

  // Task retry
  retryTask: (taskId: string) =>
    fetchJSON<Task>(`${API_BASE}/api/tasks/${taskId}/retry`, { method: 'POST' }),

  // Session cancel
  cancelSession: (sessionId: string) =>
    fetchJSON<WorkerSession>(`${API_BASE}/api/sessions/${sessionId}/cancel`, { method: 'POST' }),

  // Worker health
  getWorkerHealth: (workerId: string) =>
    fetchJSON<WorkerHealthDetail>(`${API_BASE}/api/workers/${workerId}/health`),

  // Messages
  getMessages: (projectId: string, opts?: { task_id?: string; message_type?: string }) =>
    fetchJSON<AgentMessage[]>(`${API_BASE}/api/messages?project_id=${projectId}${opts?.task_id ? `&task_id=${opts.task_id}` : ''}${opts?.message_type ? `&message_type=${opts.message_type}` : ''}`),

  getAgentInbox: (agentId: string) =>
    fetchJSON<AgentMessage[]>(`${API_BASE}/api/messages/agent/${agentId}/inbox`),

  getProjectBlockers: (projectId: string) =>
    fetchJSON<AgentMessage[]>(`${API_BASE}/api/messages/project/${projectId}/blockers`),

  getProjectHandoffs: (projectId: string) =>
    fetchJSON<AgentMessage[]>(`${API_BASE}/api/messages/project/${projectId}/handoffs`),

  // Dependencies
  getTaskDependencies: (taskId: string) =>
    fetchJSON<TaskDependency[]>(`${API_BASE}/api/dependencies/task/${taskId}`),

  getProjectDependencies: (projectId: string) =>
    fetchJSON<TaskDependency[]>(`${API_BASE}/api/dependencies/project/${projectId}`),
};
