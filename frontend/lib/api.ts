import type { Project, Task, Agent, ActivityLog, MemorySnapshot, Summary, Worker, WorkerSession, WorkerSessionDetail, WorkerLog, AutonomousDecision, HealthStatus, WorkerHealthDetail, AgentMessage, TaskDependency, BrainstormRoom, BrainstormRoomDetail, BrainstormSkill, BrainstormMessage, BrainstormSynthesis, ModelInfo, ProviderStatus, QuotaStatus, BudgetStatus, RoutingDecision, UsageRecord, Goal, GoalProgress, Run, RunDetail, RunEvent, AgentPerformance, ImprovementProposal, ApprovalGuard, ProposalConversion, ProposalSummary } from "./types";

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

  // Brainstorm Rooms
  getBrainstormRooms: (status?: string) =>
    fetchJSON<BrainstormRoom[]>(`${API_BASE}/api/brainstorms${status ? `?status=${status}` : ""}`),

  createBrainstormRoom: (data: { idea_text: string; title?: string }) =>
    fetchJSON<BrainstormRoom>(`${API_BASE}/api/brainstorms`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getBrainstormRoom: (id: string) =>
    fetchJSON<BrainstormRoomDetail>(`${API_BASE}/api/brainstorms/${id}`),

  deleteBrainstormRoom: (id: string) =>
    fetchJSON<{ deleted: boolean }>(`${API_BASE}/api/brainstorms/${id}`, {
      method: "DELETE",
    }),

  advanceBrainstormRoom: (id: string) =>
    fetchJSON<BrainstormMessage[]>(`${API_BASE}/api/brainstorms/${id}/advance`, {
      method: "POST",
    }),

  sendBrainstormMessage: (id: string, content: string, target_agent_type?: string) =>
    fetchJSON<BrainstormMessage[]>(`${API_BASE}/api/brainstorms/${id}/message`, {
      method: "POST",
      body: JSON.stringify({ content, target_agent_type }),
    }),

  skipBrainstormRoom: (id: string) =>
    fetchJSON<BrainstormRoom>(`${API_BASE}/api/brainstorms/${id}/skip`, {
      method: "POST",
    }),

  spawnBrainstormRoom: (id: string) =>
    fetchJSON<{ project_id: string; room: BrainstormRoom }>(`${API_BASE}/api/brainstorms/${id}/spawn`, {
      method: "POST",
    }),

  getBrainstormSkills: (id: string) =>
    fetchJSON<BrainstormSkill[]>(`${API_BASE}/api/brainstorms/${id}/skills`),

  updateBrainstormSkill: (roomId: string, skillId: string, status: string) =>
    fetchJSON<BrainstormSkill>(`${API_BASE}/api/brainstorms/${roomId}/skills/${skillId}`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),

  // Brainstorm Mode & Synthesis
  setBrainstormMode: (id: string, mode: string) =>
    fetchJSON<BrainstormRoom>(`${API_BASE}/api/brainstorms/${id}/mode`, {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),

  synthesizeBrainstorm: (id: string) =>
    fetchJSON<BrainstormSynthesis>(`${API_BASE}/api/brainstorms/${id}/synthesize`, {
      method: "POST",
    }),

  // ──────────────────────────────────────────────
  // Phase 3B: Model Routing / Quota / Budget
  // ──────────────────────────────────────────────

  // Models & Providers
  getModels: () => fetchJSON<ModelInfo[]>(`${API_BASE}/api/models`),
  getAvailableModels: () => fetchJSON<ModelInfo[]>(`${API_BASE}/api/models/available`),
  getProviders: () => fetchJSON<ProviderStatus[]>(`${API_BASE}/api/providers`),

  // Quota
  getQuotaStatus: () => fetchJSON<QuotaStatus[]>(`${API_BASE}/api/quota/status`),
  getProviderQuota: (provider: string) => fetchJSON<QuotaStatus>(`${API_BASE}/api/quota/${provider}`),
  resetProviderQuota: (provider: string) => fetchJSON<QuotaStatus>(`${API_BASE}/api/quota/${provider}/reset`, { method: "POST" }),
  approvePaidOverride: (data: { task_id: string; provider: string; reason: string }) =>
    fetchJSON<RoutingDecision>(`${API_BASE}/api/quota/paid-override/approve`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Budget
  getBudgetStatus: () => fetchJSON<BudgetStatus>(`${API_BASE}/api/budget/status`),
  updateBudgetConfig: (data: Partial<{ daily_soft_limit: number; daily_hard_limit: number; monthly_hard_limit: number; per_task_max_cost: number }>) =>
    fetchJSON<BudgetStatus>(`${API_BASE}/api/budget/config`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Routing
  getRoutingDecisions: (limit?: number) =>
    fetchJSON<RoutingDecision[]>(`${API_BASE}/api/routing/decisions${limit ? `?limit=${limit}` : ""}`),
  getRoutingDecision: (id: string) => fetchJSON<RoutingDecision>(`${API_BASE}/api/routing/decisions/${id}`),

  // Usage
  getUsageRecords: (limit?: number) =>
    fetchJSON<UsageRecord[]>(`${API_BASE}/api/routing/usage${limit ? `?limit=${limit}` : ""}`),

  // ──────────────────────────────────────────────
  // Phase 3C: Goal/Run Management
  // ──────────────────────────────────────────────

  // Goals
  getGoals: (projectId: string) =>
    fetchJSON<Goal[]>(`${API_BASE}/api/projects/${projectId}/goals`),

  createGoal: (projectId: string, data: { title: string; description?: string; type?: string; target_description?: string }) =>
    fetchJSON<Goal>(`${API_BASE}/api/projects/${projectId}/goals`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getGoal: (goalId: string) =>
    fetchJSON<Goal>(`${API_BASE}/api/goals/${goalId}`),

  updateGoal: (goalId: string, data: Partial<{ status: string; title: string; description: string }>) =>
    fetchJSON<Goal>(`${API_BASE}/api/goals/${goalId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  getGoalProgress: (goalId: string) =>
    fetchJSON<GoalProgress>(`${API_BASE}/api/goals/${goalId}/progress`),

  // Runs
  getProjectRuns: (projectId: string) =>
    fetchJSON<Run[]>(`${API_BASE}/api/projects/${projectId}/runs`),

  getGoalRuns: (goalId: string) =>
    fetchJSON<Run[]>(`${API_BASE}/api/goals/${goalId}/runs`),

  getTaskRuns: (taskId: string) =>
    fetchJSON<Run[]>(`${API_BASE}/api/tasks/${taskId}/runs`),

  getRun: (runId: string) =>
    fetchJSON<RunDetail>(`${API_BASE}/api/runs/${runId}`),

  getRunEvents: (runId: string) =>
    fetchJSON<RunEvent[]>(`${API_BASE}/api/runs/${runId}/events`),

  getRunPerformance: (runId: string) =>
    fetchJSON<AgentPerformance[]>(`${API_BASE}/api/runs/${runId}/performance`),

  // ──────────────────────────────────────────────
  // Phase 4: R&D / Improvement Lab
  // ──────────────────────────────────────────────

  // Analysis
  analyzeProject: (projectId: string, opts?: { goal_id?: string; analysis_types?: string[] }) =>
    fetchJSON<ImprovementProposal[]>(`${API_BASE}/api/projects/${projectId}/research/analyze`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, ...opts }),
    }),

  analyzeGoal: (goalId: string) =>
    fetchJSON<ImprovementProposal[]>(`${API_BASE}/api/goals/${goalId}/research/analyze`, {
      method: "POST",
      body: JSON.stringify({}),
    }),

  // Proposals
  getProposals: (projectId: string, status?: string) =>
    fetchJSON<ImprovementProposal[]>(`${API_BASE}/api/projects/${projectId}/proposals${status ? `?status=${status}` : ""}`),

  getProposalSummary: (projectId: string) =>
    fetchJSON<ProposalSummary>(`${API_BASE}/api/projects/${projectId}/proposals/summary`),

  getProposal: (proposalId: string) =>
    fetchJSON<ImprovementProposal>(`${API_BASE}/api/proposals/${proposalId}`),

  submitProposal: (proposalId: string) =>
    fetchJSON<ImprovementProposal>(`${API_BASE}/api/proposals/${proposalId}/submit`, {
      method: "PATCH",
    }),

  getProposalGuard: (proposalId: string) =>
    fetchJSON<ApprovalGuard>(`${API_BASE}/api/proposals/${proposalId}/guard`),

  approveProposal: (proposalId: string, guardConfirmed: boolean, notes?: string) =>
    fetchJSON<ImprovementProposal>(`${API_BASE}/api/proposals/${proposalId}/approve`, {
      method: "PATCH",
      body: JSON.stringify({ guard_confirmed: guardConfirmed, reviewer: "user", notes }),
    }),

  convertProposal: (proposalId: string) =>
    fetchJSON<ProposalConversion>(`${API_BASE}/api/proposals/${proposalId}/convert`, {
      method: "PATCH",
    }),

  rejectProposal: (proposalId: string, reason?: string) =>
    fetchJSON<ImprovementProposal>(`${API_BASE}/api/proposals/${proposalId}/reject`, {
      method: "PATCH",
      body: JSON.stringify({ reviewer: "user", notes: reason }),
    }),

  archiveProposal: (proposalId: string) =>
    fetchJSON<ImprovementProposal>(`${API_BASE}/api/proposals/${proposalId}/archive`, {
      method: "PATCH",
    }),
};
