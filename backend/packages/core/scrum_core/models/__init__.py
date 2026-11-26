"""SQLAlchemy ORM models (plan §4). Every tenant table carries ``org_id`` and is protected by RLS."""

from scrum_core.models.audit import AuditLog
from scrum_core.models.base import Base
from scrum_core.models.blocker import ActionTokenUse, Blocker, BlockerEvent, BlockerEvidence, Dependency, ReviewItem
from scrum_core.models.org import Integration, Organization, User
from scrum_core.models.session import (
    AsyncCheckin,
    Attendance,
    MemberUpdateRow,
    Notification,
    Report,
    StandupSession,
    TranscriptSegment,
)
from scrum_core.models.team import Question, QuestionTemplate, Schedule, Team, TeamMember

__all__ = [
    "ActionTokenUse",
    "AsyncCheckin",
    "Attendance",
    "AuditLog",
    "Base",
    "Blocker",
    "BlockerEvent",
    "BlockerEvidence",
    "Dependency",
    "Integration",
    "MemberUpdateRow",
    "Notification",
    "Organization",
    "Question",
    "QuestionTemplate",
    "Report",
    "ReviewItem",
    "Schedule",
    "StandupSession",
    "Team",
    "TeamMember",
    "TranscriptSegment",
    "User",
]

TENANT_TABLES: list[str] = [
    t.name for t in Base.metadata.sorted_tables if "org_id" in t.c and t.name != "organizations"
]
