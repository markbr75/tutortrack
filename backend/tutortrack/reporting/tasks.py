"""Celery tasks (thin): the daily FX rate fetch is global platform housekeeping (Beat)."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="tutortrack.reporting.tasks.fetch_fx_rates", ignore_result=True)
def fetch_fx_rates() -> int:
    from .fx import fetch_latest

    return fetch_latest()
