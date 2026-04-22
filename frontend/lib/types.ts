export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface Task {
  id: string;
  project_id: string;
  content: string;
  status: "pending" | "assigned" | "in_progress" | "completed" | "failed";
  assigned_agent_id: string | null;
  parent_task_id: string | null;
  created_at: string;
  updated_at: string;
  retry_count: number;
}

export interface Agent {
  id: string;
  name: string;
  type: "orchestrator" | "backend" | "frontend" | "qa" | "docs" | "memory";
  status: "idle" | "working" | "error";
  current_task_id: string | null;
}

export interface ActivityLog {
  id: string;
  project_id: string;
  agent_id: string | null;
  action: string;
  details: string;
  timestamp: string;
}

export interface MemorySnapshot {
  id: string;
  project_id: string;
  last_completed: string;
  current_blocker: string;
  next_step: string;
  updated_at: string;
}

export interface Summary {
  project_name: string;
  total_tasks: number;
  completed_tasks: number;
  in_progress_tasks: number;
  pending_tasks: number;
  agents: {
    name: string;
    type: string;
    status: string;
  }[];
  recent_activity: ActivityLog[];
  memory: MemorySnapshot | null;
  overall_status: "healthy" | "blocked" | "idle";
  message: string;
}

export interface Worker {
  id: string;
  name: string;
  hostname: string;
  platform: string;
  status: 'online' | 'offline' | 'busy';
  last_heartbeat: string;
  created_at: string;
}

export interface WorkerSession {
  id: string;
  worker_id: string;
  task_id: string;
  agent_id: string | null;
  status: 'idle' | 'running' | 'waiting_input' | 'completed' | 'error';
  last_output: string | null;
  waiting_for_input: boolean;
  input_type: 'enter' | 'yes_no' | 'text' | 'none' | null;
  input_prompt_text: string | null;
  exit_code: number | null;
  created_at: string;
  updated_at: string;
}

export interface WorkerLog {
  id: string;
  session_id: string;
  level: 'info' | 'warn' | 'error' | 'output';
  content: string;
  timestamp: string;
}

export interface AutonomousDecision {
  id: string;
  session_id: string;
  decision: string;
  reason: string;
  auto_resolved: boolean;
  timestamp: string;
}

export interface WorkerSessionDetail extends WorkerSession {
  logs: WorkerLog[];
  decisions: AutonomousDecision[];
}

export interface HealthStatus {
  status: string;
  online_workers: number;
  active_sessions: number;
}

export interface WorkerHealthDetail {
  id: string;
  name: string;
  status: string;
  last_heartbeat: string;
  active_sessions: number;
  total_sessions: number;
}
