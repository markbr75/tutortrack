import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { flushNow, isOffline, queueChange, useOutbox } from "../offline/client";
import type { ReportBody } from "../offline/outbox";
import { ReportFieldInput, type Answers } from "./ReportPage";

/** A lesson report written without a signal (E16-T08, FR-16-3): the form comes from the
 * offline pack the phone keeps for the next week; the save waits in the outbox and opens
 * the report on the server when it syncs. */
export function OfflineReportPage({ lessonId }: { lessonId: string }) {
  const { t } = useTranslation();
  const pack = useQuery({
    queryKey: ["tutor", "offline"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/offline")),
  });
  const queued = useOutbox().filter(
    (item) => item.lessonId === lessonId && item.kind === "report.save",
  );
  const lastQueued = queued.at(-1);
  const lesson = pack.data?.lessons.find((l) => l.id === lessonId);
  const [answers, setAnswers] = useState<Answers | null>(null);
  const current =
    answers ??
    (lastQueued ? (lastQueued.body as ReportBody).answers : (lesson?.report?.answers ?? {}));

  const save = useMutation({
    mutationFn: async (submit: boolean) => {
      await queueChange({
        kind: "report.save",
        label: lesson?.title ?? "",
        lessonId,
        reportId: lesson?.report?.id ?? null,
        body: { answers: current, submit },
        etag: lesson?.report?.etag ?? null,
      });
      if (!isOffline()) await flushNow();
      return submit;
    },
  });

  if (pack.isPending) return <Spinner label={t("grid.loading")} />;
  if (!lesson) {
    return (
      <Alert tone="warning" title={t("pwa.notOnPhone")}>
        <Link to="/tutor/lessons/$lessonId" params={{ lessonId }} className="underline">
          {t("pwa.backToLesson")}
        </Link>
      </Alert>
    );
  }
  const written = lesson.report?.status === "submitted" || lesson.report?.status === "approved";
  return (
    <form
      className="space-y-4"
      aria-label={lesson.title}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(true);
      }}
    >
      <h1 className="text-xl font-semibold">{t("tutor.reportFor", { title: lesson.title })}</h1>
      <Alert>{t("pwa.reportOnPhone")}</Alert>
      {lesson.report_fields.map((field) => (
        <ReportFieldInput
          key={field.key}
          field={field}
          value={current[field.key]}
          disabled={written}
          onChange={(v) => setAnswers({ ...current, [field.key]: v })}
        />
      ))}
      {written ? (
        <Alert tone="success">{t("tutor.reportSubmitted")}</Alert>
      ) : (
        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending}>
            {t("tutor.submitReport")}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={save.isPending}
            onClick={() => save.mutate(false)}
          >
            {t("tutor.saveDraft")}
          </Button>
        </div>
      )}
      {save.isSuccess ? (
        <Alert tone="success">{t(save.data ? "pwa.reportQueuedSubmit" : "pwa.reportQueued")}</Alert>
      ) : null}
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </form>
  );
}
