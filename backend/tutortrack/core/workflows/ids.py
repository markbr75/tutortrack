"""Deterministic, tenant-prefixed workflow ids (E32 FR-32-3): ``process:org:part...``.

Starting a workflow whose id is already running is rejected, which makes starts
idempotent (e.g. two ``invoice.issued`` deliveries start one dunning workflow).
"""

from __future__ import annotations

from typing import Any


def workflow_id(process: str, organisation_id: Any, *parts: Any) -> str:
    if ":" in process:
        raise ValueError("process must not contain ':'")
    return ":".join([process, str(organisation_id), *(str(p) for p in parts)])


def parse(workflow_id_value: str) -> tuple[str, str, list[str]]:
    process, org, *rest = workflow_id_value.split(":")
    return process, org, rest
