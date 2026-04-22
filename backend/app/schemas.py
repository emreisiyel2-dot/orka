from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ---------- Project ----------

class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    created_at: datetime


# ---------- Task ----------

class TaskCreate(BaseModel):
    project_id: str
    content: str
    parent_task_id: Optional[str] = None


class TaskAssign(BaseModel):
    agent_id: str


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    content: str
    status: str
    assigned_agent_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------- Agent ----------

class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str
    status: str
    current_task_id: Optional[str] = None
    created_at: datetime


class AgentStatusUpdate(BaseModel):
    status: str


# ---------- Activity Log ----------

class ActivityLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    agent_id: Optional[str] = None
    action: str
    details: str
    timestamp: datetime


# ---------- Memory Snapshot ----------

class MemorySnapshotCreate(BaseModel):
    last_completed: Optional[str] = None
    current_blocker: Optional[str] = None
    next_step: Optional[str] = None


class MemorySnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    last_completed: Optional[str] = None
    current_blocker: Optional[str] = None
    next_step: Optional[str] = None
    updated_at: datetime


# ---------- Summary ----------

class AgentSummary(BaseModel):
    name: str
    type: str
    status: str


class SummaryResponse(BaseModel):
    project_name: str
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    agents: list[AgentSummary]
    recent_activity: list[ActivityLogResponse]
    memory: Optional[MemorySnapshotResponse] = None
    overall_status: str
    message: str
