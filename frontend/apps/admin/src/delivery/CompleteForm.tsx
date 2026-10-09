import { ApiError, unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { fromInputs, toDateInput, toTimeInput } from "../calendar/dates";

type Outcome = components["schemas"]["AttendanceOutcomeEnum"];
const OUTCOMES: Outcome[] = ["present", "late", "absent_notified", "no_show"];

interface Row {
  outcome: Outcome;
  late: string;
}

function insufficientBalance(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.problem as { code?: string }).code === "insufficient_balance"
  );
}

/** Complete a lesson with a register (FR-09-1/2): one outcome per student, "all present",
 * optional actual times, and the prepaid-balance override for staff. */
export function CompleteForm({ lessonId, onDone }: { lessonId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const canOverride = usePermission("delivery.balance.override");
  const lesson = useQuery({
    queryKey: ["lesson", lessonId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/lessons/{id}", { params: { path: { id: lessonId } } })),
  });
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [actual, setActual] = useState({ start: "", end: "" });
  const [override, setOverride] = useState(false);

  const attendees = lesson.data?.attendees ?? [];
  const rowOf = (id: string): Row => rows[id] ?? { outcome: "present", late: "" };
  const setRow = (id: string, change: Partial<Row>) =>
    setRows((current) => ({ ...current, [id]: { ...rowOf(id), ...change } }));

  const save = useMutation({
    mutationFn: async () => {
      const day = lesson.data ? toDateInput(new Date(lesson.data.start)) : "";
      return unwrap(
        await api.POST("/api/v1/lessons/{id}/complete", {
          params: { path: { id: lessonId } },
          body: {
            attendance: attendees.map((a) => ({
              attendee: a.id,
              outcome: rowOf(a.id).outcome,
              late_minutes:
                rowOf(a.id).outcome === "late" && rowOf(a.id).late
                  ? Number(rowOf(a.id).late)
                  : null,
            })),
            actual_start:
              actual.start && actual.end ? fromInputs(day, actual.start).toISOString() : null,
            actual_end:
              actual.start && actual.end ? fromInputs(day, actual.end).toISOString() : null,
            override_balance: override,
          },
        }),
      );
    },
    onSuccess: onDone,
  });

  if (lesson.isPending) return <Spinner className="mt-4 size-5" label={t("grid.loading")} />;
  return (
    <form
      className="mt-4 space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <fieldset>
        <legend className="text-sm font-semibold">{t("delivery.complete.title")}</legend>
        <ul className="mt-2 space-y-2">
          {attendees.map((a) => (
            <li key={a.id} className="grid grid-cols-[1fr_auto] items-end gap-2">
              <SelectField
                label={t("delivery.complete.outcomeFor", { name: a.name })}
                value={rowOf(a.id).outcome}
                onChange={(e) => setRow(a.id, { outcome: e.target.value as Outcome })}
                options={OUTCOMES.map((o) => ({ value: o, label: t(`delivery.outcome.${o}`) }))}
              />
              {rowOf(a.id).outcome === "late" ? (
                <TextField
                  className="w-24"
                  type="number"
                  min={0}
                  max={600}
                  label={t("delivery.complete.lateMinutesFor", { name: a.name })}
                  value={rowOf(a.id).late}
                  onChange={(e) => setRow(a.id, { late: e.target.value })}
                />
              ) : (
                <span />
              )}
            </li>
          ))}
        </ul>
        {attendees.length > 1 ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="mt-1"
            onClick={() => setRows({})}
          >
            {t("delivery.complete.allPresent")}
          </Button>
        ) : null}
      </fieldset>
      <details>
        <summary className="cursor-pointer text-sm">{t("delivery.complete.actualTimes")}</summary>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <TextField
            type="time"
            step={300}
            label={t("delivery.complete.actualStart")}
            value={actual.start}
            placeholder={lesson.data ? toTimeInput(new Date(lesson.data.start)) : undefined}
            onChange={(e) => setActual((v) => ({ ...v, start: e.target.value }))}
          />
          <TextField
            type="time"
            step={300}
            label={t("delivery.complete.actualEnd")}
            value={actual.end}
            onChange={(e) => setActual((v) => ({ ...v, end: e.target.value }))}
          />
        </div>
      </details>
      {insufficientBalance(save.error) ? (
        <Alert tone="warning">
          {save.error instanceof Error ? save.error.message : null}
          {canOverride ? (
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={override}
                onChange={(e) => setOverride(e.target.checked)}
              />
              {t("delivery.complete.overrideBalance")}
            </label>
          ) : null}
        </Alert>
      ) : (
        <ErrorList error={save.error} />
      )}
      <Button type="submit" disabled={save.isPending}>
        {t("delivery.complete.save")}
      </Button>
    </form>
  );
}
