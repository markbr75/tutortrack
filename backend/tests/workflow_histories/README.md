# Recorded workflow histories (E32 FR-32-8)

Each `<WorkflowType>-<case>.json` is a real event history. `test_replay_recorded_history`
style tests replay them against the current workflow code with Temporal's `Replayer`, so a
change that would break in-flight executions (non-determinism) fails CI. Fix it with
`workflow.patched()` or Worker Versioning, never by re-recording to make CI green.

Record or add a history when a workflow ships or deliberately changes shape:

```bash
cd backend
RECORD_WORKFLOW_HISTORIES=1 uv run pytest tutortrack/workflows/tests -k waits_in_tenant_time
```

Histories are written with the development payload key (payloads are encrypted), which the
test settings also use.
