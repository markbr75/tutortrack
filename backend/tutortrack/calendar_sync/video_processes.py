"""``RecordingFetchWorkflow`` ``recordings:{org}:{lesson}`` (E22-T10).

Started by ``lesson.completed`` for online lessons whose provider keeps recordings
(Zoom cloud recording, Daily, Lessonspace). Providers take a while to process a
recording, so it asks after 15 minutes, 1 hour, 6 hours and 24 hours, stopping once one
arrives (or when the Zoom ``recording.completed`` webhook already stored it, signal
``stored``). Replaces a "fetch pending recordings" sweeper.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step

TIMEOUT = timedelta(minutes=5)
RECORDINGS_PROCESS = "recordings"
WAITS = (timedelta(minutes=15), timedelta(minutes=45), timedelta(hours=5), timedelta(hours=18))
RETRY = RetryPolicy(initial_interval=timedelta(seconds=30), maximum_attempts=4)


def recordings_workflow_id(org: object, lesson_id: object) -> str:
    return workflow_id(RECORDINGS_PROCESS, org, lesson_id)


@dataclass(frozen=True, kw_only=True)
class RecordingsInput(WorkflowInput):
    lesson_id: str


@tenant_activity
def fetch_lesson_recordings(input: RecordingsInput) -> int:
    from . import video

    return video.fetch_recordings(input.lesson_id)


@register_workflow(process=RECORDINGS_PROCESS, task_queue="integrations", cancel_permission=None)
@workflow.defn
class RecordingFetchWorkflow:
    def __init__(self) -> None:
        self.stored = False

    @workflow.signal(name="stored")
    def mark_stored(self) -> None:
        self.stored = True

    @workflow.run
    async def run(self, input: RecordingsInput) -> str:
        found = 0
        for wait in WAITS:
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.stored, timeout=wait)
            if self.stored:
                break
            found = await workflow.execute_activity(
                fetch_lesson_recordings,
                input,
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
            )
            if found:
                break
        result = "webhook" if self.stored else f"found:{found}"
        await report_step(input, result, status="completed")
        return result
