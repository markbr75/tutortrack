import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { api, usePermission } from "../api";
import { CancelForm } from "../delivery/CancelForm";
import { CompleteForm } from "../delivery/CompleteForm";
import { fromInputs, toDateInput, toTimeInput, viewerTimeZone } from "./dates";
import { ErrorList } from "./ErrorList";
import { type CalendarItem, conflictsOf } from "./types";

function Pricing({ id }: { id: string }) {
  const { t } = useTranslation();
  const pricing = useQuery({
    queryKey: ["lesson", id, "pricing"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/lessons/{id}/pricing", { params: { path: { id } } })),
  });
  const data = pricing.data as unknown as
    { charges?: { trace: string[] }[]; pay?: { trace: string[] }[] } | undefined;
  if (!data) return null;
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer">{t("calendar.pricing")}</summary>
      <ul className="mt-1 list-disc pl-5 text-muted-foreground">
        {[...(data.charges ?? []), ...(data.pay ?? [])].map((line, i) => (
          <li key={i}>{line.trace.join(" · ")}</li>
        ))}
      </ul>
    </details>
  );
}

/** The lesson quick view (FR-08-7): details and actions, including a keyboard-friendly
 * reschedule form as the alternative to dragging. */
export function QuickView({ item, onClose }: { item: CalendarItem | null; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDialogElement>(null);
  const canEdit = usePermission("scheduling.lesson.edit");
  const canCancel = usePermission("scheduling.lesson.cancel");
  const canComplete = usePermission("scheduling.lesson.complete");
  const canOverride = usePermission("scheduling.override_conflicts");
  const canReport = usePermission("delivery.report.write");
  const navigate = useNavigate();
  const canSeeCharge = usePermission("billing.rates.view_charge");
  const canSeePay = usePermission("billing.rates.view_pay");
  const canPrice = canSeeCharge || canSeePay;
  const [mode, setMode] = useState<"view" | "cancel" | "reschedule" | "complete">("view");
  const [reason, setReason] = useState("");
  const [when, setWhen] = useState({ date: "", start: "", end: "" });

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (item && !dialog.open) dialog.showModal();
    if (!item && dialog.open) dialog.close();
    if (item) {
      const start = new Date(item.start);
      setWhen({
        date: toDateInput(start),
        start: toTimeInput(start),
        end: toTimeInput(new Date(item.end)),
      });
      setMode("view");
      setReason("");
    }
  }, [item]);

  const done = () => {
    void queryClient.invalidateQueries({ queryKey: ["calendar"] });
    onClose();
  };
  const run = useMutation({
    mutationFn: async (kind: "missed" | "reschedule" | "override") => {
      const id = item!.id;
      const path = { params: { path: { id } } };
      if (kind === "missed")
        return unwrap(await api.POST("/api/v1/lessons/{id}/missed", { ...path, body: { reason } }));
      return unwrap(
        await api.POST("/api/v1/lessons/{id}/reschedule", {
          ...path,
          body: {
            start: fromInputs(when.date, when.start).toISOString(),
            end: fromInputs(when.date, when.end).toISOString(),
            reason,
            notify: true,
            override_conflicts: kind === "override",
          },
        }),
      );
    },
    onSuccess: done,
  });
  const openReport = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/lessons/{lesson_id}/reports", {
          params: { path: { lesson_id: item!.id } },
          body: {},
        }),
      ),
    onSuccess: (report) => {
      onClose();
      void navigate({ to: "/reports/$reportId", params: { reportId: report.id } });
    },
  });

  const lesson = item?.kind === "lesson";
  const planned = item?.status === "planned";
  const started = item ? new Date(item.start) <= new Date() : false;
  const otherTz = item && item.timezone !== viewerTimeZone();
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="quick-view-title"
      className="w-full max-w-md rounded-lg border border-border bg-background p-5 shadow-lg backdrop:bg-black/40"
    >
      {item ? (
        <div>
          <h2 id="quick-view-title" className="text-lg font-semibold">
            {item.title}
          </h2>
          <p className="text-sm text-muted-foreground">
            {formatDateTime(item.start, i18n.language)} –{" "}
            {new Date(item.end).toLocaleTimeString(i18n.language, {
              hour: "2-digit",
              minute: "2-digit",
            })}
            {otherTz
              ? ` (${formatDateTime(item.start, i18n.language, item.timezone)} ${item.timezone})`
              : ""}
          </p>
          <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">{t("calendar.statusLabel")}</dt>
            <dd>{t(`calendar.status.${item.status}`, { defaultValue: item.status })}</dd>
            {item.tutors.length ? (
              <>
                <dt className="text-muted-foreground">{t("calendar.tutors")}</dt>
                <dd>{item.tutors.map((p) => p.name).join(", ")}</dd>
              </>
            ) : null}
            {item.students.length ? (
              <>
                <dt className="text-muted-foreground">{t("calendar.students")}</dt>
                <dd>{item.students.map((p) => p.name).join(", ")}</dd>
              </>
            ) : null}
            {item.online || item.location ? (
              <>
                <dt className="text-muted-foreground">{t("calendar.where")}</dt>
                <dd>{item.online ? t("calendar.online") : item.location}</dd>
              </>
            ) : null}
          </dl>
          {item.job ? (
            <p className="mt-2 text-sm">
              <Link
                className="underline-offset-2 hover:underline"
                to="/jobs/$jobId"
                params={{ jobId: item.job }}
              >
                {t("calendar.openJob")}
              </Link>
            </p>
          ) : null}
          {lesson && canPrice ? <Pricing id={item.id} /> : null}
          {item.locked ? <Alert className="mt-3">{t("calendar.locked")}</Alert> : null}

          {mode === "cancel" ? (
            <CancelForm lessonId={item.id} inSeries={Boolean(item.series)} onDone={done} />
          ) : null}
          {mode === "complete" ? <CompleteForm lessonId={item.id} onDone={done} /> : null}
          {mode === "reschedule" ? (
            <form
              className="mt-4 grid grid-cols-3 gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                run.mutate("reschedule");
              }}
            >
              <TextField
                label={t("calendar.date")}
                type="date"
                value={when.date}
                onChange={(e) => setWhen((w) => ({ ...w, date: e.target.value }))}
              />
              <TextField
                label={t("calendar.from")}
                type="time"
                step={300}
                value={when.start}
                onChange={(e) => setWhen((w) => ({ ...w, start: e.target.value }))}
              />
              <TextField
                label={t("calendar.to")}
                type="time"
                step={300}
                value={when.end}
                onChange={(e) => setWhen((w) => ({ ...w, end: e.target.value }))}
              />
              <div className="col-span-3">
                <TextField
                  label={t("calendar.reason")}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </div>
              <div className="col-span-3 flex gap-2">
                <Button type="submit" disabled={run.isPending}>
                  {t("calendar.move")}
                </Button>
                {conflictsOf(run.error).length && canOverride ? (
                  <Button type="button" variant="secondary" onClick={() => run.mutate("override")}>
                    {t("calendar.scheduleAnyway")}
                  </Button>
                ) : null}
              </div>
            </form>
          ) : null}
          <ErrorList error={run.error ?? openReport.error} />

          <div className="mt-5 flex flex-wrap gap-2">
            {lesson && planned && !item.locked && canComplete && started && mode !== "complete" ? (
              <>
                <Button size="sm" onClick={() => setMode("complete")}>
                  {t("calendar.complete")}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => run.mutate("missed")}
                  disabled={run.isPending}
                >
                  {t("calendar.missed")}
                </Button>
              </>
            ) : null}
            {lesson && planned && !item.locked && canEdit && mode !== "reschedule" ? (
              <Button size="sm" variant="secondary" onClick={() => setMode("reschedule")}>
                {t("calendar.reschedule")}
              </Button>
            ) : null}
            {lesson && planned && !item.locked && canCancel && mode !== "cancel" ? (
              <Button size="sm" variant="secondary" onClick={() => setMode("cancel")}>
                {t("calendar.cancel")}
              </Button>
            ) : null}
            {lesson && canReport && item.status !== "cancelled" && item.tutors.length ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => openReport.mutate()}
                disabled={openReport.isPending}
              >
                {t("calendar.writeReport")}
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={onClose}>
              {t("calendar.close")}
            </Button>
          </div>
        </div>
      ) : null}
    </dialog>
  );
}
