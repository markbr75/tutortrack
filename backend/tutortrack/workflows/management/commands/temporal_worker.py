import asyncio
from typing import Any

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tutortrack.core.workflows.client import connect
from tutortrack.core.workflows.worker import build_workers

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Run Temporal workers for the given task queue(s) ('all' = every queue)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--task-queue", action="append", default=[], dest="queues")
        parser.add_argument("--max-activity-threads", type=int, default=20)

    def handle(self, *args: Any, **options: Any) -> None:
        queues = options["queues"] or ["all"]
        if "all" in queues:
            queues = list(settings.TEMPORAL["TASK_QUEUES"])
        unknown = set(queues) - set(settings.TEMPORAL["TASK_QUEUES"])
        if unknown:
            raise CommandError(f"Unknown task queue(s): {', '.join(sorted(unknown))}")
        asyncio.run(self._run(queues, options["max_activity_threads"]))

    async def _run(self, queues: list[str], threads: int) -> None:
        client = await connect()
        workers = build_workers(client, queues, max_activity_threads=threads)
        if not workers:
            raise CommandError("No workflows or activities registered for these queues.")
        names = [w.task_queue for w in workers]
        self.stdout.write(f"Temporal workers polling: {', '.join(names)}")
        logger.info("temporal.worker_started", task_queues=names)
        await asyncio.gather(*(w.run() for w in workers))
