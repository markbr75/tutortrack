"""Worker interceptors: report activity and workflow failures to Sentry with tenant tags
(tracing uses temporalio.contrib.opentelemetry when OTEL is configured)."""

from __future__ import annotations

from typing import Any

import sentry_sdk  # imported here, outside the workflow sandbox
from temporalio import activity, client, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)


def _capture(exc: BaseException, **tags: Any) -> None:
    with sentry_sdk.new_scope() as scope:
        for key, value in tags.items():
            scope.set_tag(key, str(value))
        sentry_sdk.capture_exception(exc)


class _ActivityInbound(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        try:
            return await super().execute_activity(input)
        except Exception as exc:
            info = activity.info()
            org = getattr(input.args[0], "organisation_id", None) if input.args else None
            _capture(
                exc,
                workflow_id=info.workflow_id,
                workflow_type=info.workflow_type,
                activity=info.activity_type,
                attempt=info.attempt,
                organisation_id=org,
            )
            raise


class _WorkflowInbound(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        try:
            return await super().execute_workflow(input)
        except Exception as exc:
            if not workflow.unsafe.is_replaying():
                with workflow.unsafe.sandbox_unrestricted():
                    info = workflow.info()
                    _capture(exc, workflow_id=info.workflow_id, workflow_type=info.workflow_type)
            raise


class SentryInterceptor(client.Interceptor, Interceptor):
    """Registered on the client; workers created from that client pick it up too."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _ActivityInbound(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _WorkflowInbound
