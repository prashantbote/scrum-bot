"""TranscriptWriter: buffers segments and batch-inserts them (flushed per member and at the end)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from uuid import UUID

from scrum_core.db import session_for
from scrum_core.models import TranscriptSegment


@dataclass
class Segment:
    speaker_user_id: UUID | None
    speaker_label: str
    question_id: UUID | None
    start_ms: int
    end_ms: int
    text: str
    confidence: float = 1.0
    speaker_confidence: float = 1.0
    id: UUID = field(default_factory=uuid.uuid4)


class TranscriptWriter:
    def __init__(self, org_id: UUID, session_id: UUID) -> None:
        self.org_id, self.session_id = org_id, session_id
        self._buffer: list[Segment] = []
        self.count = 0
        self.all: list[Segment] = []

    def add(self, seg: Segment) -> Segment:
        self._buffer.append(seg)
        self.all.append(seg)
        return seg

    async def flush(self) -> None:
        if not self._buffer:
            return
        rows, self._buffer = self._buffer, []
        async with session_for(self.org_id) as db:
            db.add_all(
                [
                    TranscriptSegment(
                        id=s.id,
                        org_id=self.org_id,
                        session_id=self.session_id,
                        speaker_user_id=s.speaker_user_id,
                        speaker_label=s.speaker_label,
                        question_id=s.question_id,
                        start_ms=s.start_ms,
                        end_ms=s.end_ms,
                        text=s.text,
                        confidence=round(s.confidence, 3),
                        speaker_confidence=s.speaker_confidence,
                    )
                    for s in rows
                ]
            )
        self.count += len(rows)
