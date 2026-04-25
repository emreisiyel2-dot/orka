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

export interface AgentMessage {
  id: string;
  project_id: string;
  task_id: string | null;
  from_agent_id: string;
  to_agent_id: string;
  message_type: 'handoff' | 'request_info' | 'response' | 'blocker' | 'update' | 'complete';
  content: string;
  context: string | null;
  status: 'pending' | 'read' | 'acted_on';
  created_at: string;
  from_agent_name: string | null;
  to_agent_name: string | null;
}

export interface TaskDependency {
  id: string;
  task_id: string;
  depends_on_task_id: string;
  status: 'pending' | 'satisfied';
  created_at: string;
  satisfied_at: string | null;
  task_content: string | null;
  depends_on_content: string | null;
}

// ──────────────────────────────────────────────
// Phase 3A: Brainstorm System
// ──────────────────────────────────────────────

export type BrainstormStatus = "brainstorming" | "refining" | "ready_to_spawn" | "spawned";

export interface BrainstormRoom {
  id: string;
  title: string;
  idea_text: string;
  status: BrainstormStatus;
  current_round: number;
  max_rounds: number;
  project_id: string | null;
  spawn_plan: string | null;
  created_at: string;
  updated_at: string;
  mode: BrainstormMode;
  synthesis: string | null;
}

export interface BrainstormAgent {
  id: string;
  agent_type: string;
  agent_name: string;
  status: "active" | "paused" | "completed";
  turn_order: number;
}

export type BrainstormMsgRole = "user" | "agent" | "system";
export type BrainstormMsgType = "idea" | "question" | "analysis" | "risk" | "suggestion" | "plan" | "challenge" | "response" | "tradeoff" | "alternative" | "deep_dive" | "convergence" | "synthesis";

export interface BrainstormMessage {
  id: string;
  room_id: string;
  agent_id: string | null;
  agent_type: string | null;
  role: BrainstormMsgRole;
  content: string;
  message_type: BrainstormMsgType;
  round_number: number;
  created_at: string;
}

export type BrainstormSkillStatus = "suggested" | "accepted" | "rejected" | "locked";

export interface BrainstormSkill {
  id: string;
  skill_name: string;
  description: string;
  relevance_reason: string;
  status: BrainstormSkillStatus;
}

export interface BrainstormRoomDetail extends BrainstormRoom {
  messages: BrainstormMessage[];
  agents: BrainstormAgent[];
  skills: BrainstormSkill[];
}

export type BrainstormMode = "normal" | "deep_dive" | "exploration" | "decision";

export interface BrainstormSynthesis {
  round_reached: number;
  total_messages: number;
  key_decisions: string[];
  risks_identified: string[];
  open_questions: string[];
  suggested_actions: string[];
  summary_text: string;
}

// ──────────────────────────────────────────────
// Phase 3B: Model Routing / Quota / Budget
// ──────────────────────────────────────────────

export interface ModelInfo {
  id: string;
  provider: string;
  tier: "low" | "medium" | "high";
  cost_per_1k_input: number;
  cost_per_1k_output: number;
  max_tokens: number;
  strengths: string[];
  speed: "fast" | "medium" | "slow";
}

export interface ProviderStatus {
  name: string;
  healthy: boolean;
  quota_status: "available" | "throttled" | "exhausted" | "unavailable";
  remaining_quota: number | null;
  total_quota: number | null;
  reset_at: string | null;
  allow_paid_overage: boolean;
  models: ModelInfo[];
}

export interface QuotaStatus {
  id: string;
  provider: string;
  quota_type: string;
  status: "available" | "throttled" | "exhausted";
  remaining_quota: number | null;
  total_quota: number | null;
  reset_at: string | null;
  allow_paid_overage: boolean;
  updated_at: string;
}

export interface BudgetStatus {
  daily_spend: number;
  daily_soft_limit: number;
  daily_hard_limit: number;
  monthly_spend: number;
  monthly_hard_limit: number;
  state: "normal" | "throttled" | "blocked";
}

export interface RoutingDecision {
  id: string;
  task_id: string | null;
  agent_type: string | null;
  requested_tier: string;
  selected_model: string;
  selected_provider: string;
  reason: string;
  fallback_from: string | null;
  quota_status: string;
  cost_estimate: number;
  actual_cost: number | null;
  blocked_reason: string | null;
  created_at: string;
}

export interface UsageRecord {
  id: string;
  task_id: string | null;
  agent_type: string | null;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  routing_decision_id: string | null;
  created_at: string;
}

// ──────────────────────────────────────────────
// Phase 3C: Goal/Run Management
// ──────────────────────────────────────────────

export interface Goal {
  id: string;
  project_id: string;
  title: string;
  description: string;
  status: "planned" | "active" | "completed" | "paused" | "abandoned";
  type: "execution" | "research" | "improvement";
  source: "user" | "brainstorm" | "auto";
  source_goal_id: string | null;
  target_description: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface GoalProgress {
  goal_id: string;
  total_tasks: number;
  completed_tasks: number;
  progress_percent: number;
  status: string;
}

export interface Run {
  id: string;
  task_id: string;
  goal_id: string | null;
  project_id: string;
  agent_type: string;
  worker_session_id: string | null;
  routing_decision_id: string | null;
  provider: string;
  model: string;
  execution_mode: "cli" | "api" | "simulated";
  status: "pending" | "running" | "completed" | "failed" | "retrying" | "cancelled" | "blocked" | "paused";
  retry_count: number;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  failure_type: string | null;
  evaluator_status: "pending" | "passed" | "failed" | "skipped" | null;
  created_at: string;
  updated_at: string;
}

export interface RunDetail extends Run {
  events: RunEvent[];
}

export interface RunEvent {
  id: string;
  run_id: string;
  event_type: string;
  execution_mode: string | null;
  provider: string | null;
  model: string | null;
  message: string;
  metadata_json: string | null;
  created_at: string;
}

export interface AgentPerformance {
  agent_type: string;
  total_runs: number;
  completed: number;
  failed: number;
  success_rate: number;
  avg_duration_seconds: number;
  retry_rate: number;
  by_execution_mode: Record<string, number>;
  by_provider: Record<string, number>;
}

// ──────────────────────────────────────────────
// Phase 4: R&D / Improvement Lab
// ──────────────────────────────────────────────

export interface ImprovementProposal {
  id: string;
  project_id: string;
  source_goal_id: string | null;
  title: string;
  status: "draft" | "under_review" | "approved" | "rejected" | "converted_to_goal" | "archived";
  problem_description: string;
  evidence_summary: string;
  suggested_solution: string;
  expected_impact: string;
  risk_level: "low" | "medium" | "high" | "critical";
  implementation_effort: "trivial" | "simple" | "moderate" | "complex" | "major";
  analysis_type: string;
  affected_agents: string;
  affected_areas: string;
  related_run_ids: string;
  related_goal_ids: string;
  related_task_ids: string;
  related_agent_type: string | null;
  related_provider: string | null;
  related_model: string | null;
  guard_quota_impact: string;
  guard_risk_assessment: string;
  guard_approved_by: string | null;
  guard_approved_at: string | null;
  reviewed_by: string | null;
  review_notes: string | null;
  reviewed_at: string | null;
  implementation_goal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApprovalGuard {
  estimated_runs: number;
  estimated_cost_usd: number;
  requires_paid_provider: boolean;
  budget_remaining_usd: number;
  budget_fits: boolean;
  risk_level: string;
  affected_systems: string[];
  has_breaking_changes: boolean;
  rollback_possible: boolean;
  rollback_plan: string;
  can_proceed: boolean;
  warnings: string[];
  blocks: string[];
}

export interface ProposalConversion {
  proposal: ImprovementProposal;
  implementation_goal: Goal;
  tasks_created: number;
}

export interface ProposalSummary {
  project_id: string;
  counts: Record<string, number>;
  total: number;
  recent_proposals: { id: string; title: string; status: string; risk_level: string }[];
}
