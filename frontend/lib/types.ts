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
