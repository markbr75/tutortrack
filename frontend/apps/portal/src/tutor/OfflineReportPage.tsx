import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { PortalHeader } from "../layout/PortalPage";
import { flushNow, isOffline, queueChange, useOutbox } from "../offline/client";
import type { ReportBody } from "../offline/outbox";
import { ReportForm, type Answers } from "./ReportPage";

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
        <Link
          to="/tutor/lessons/$lessonId"
          params={{ lessonId }}
          className="font-medium text-link underline-offset-2 hover:underline"
        >
          {t("pwa.backToLesson")}
        </Link>
      </Alert>
    );
  }
  const written = lesson.report?.status === "submitted" || lesson.report?.status === "approved";
  return (
    <div>
      <PortalHeader
        back={
          <Link to="/tutor/lessons/$lessonId" params={{ lessonId }}>
            {lesson.title}
          </Link>
        }
        title={t("tutor.reportFor", { title: lesson.title })}
      />
      <ReportForm
        label={lesson.title}
        fields={lesson.report_fields}
        answers={current}
        written={written}
        pending={save.isPending}
        lead={<Alert>{t("pwa.reportOnPhone")}</Alert>}
        onChange={(key, v) => setAnswers({ ...current, [key]: v })}
        onSubmit={() => save.mutate(true)}
        onDraft={() => save.mutate(false)}
      >
        {save.isSuccess ? (
          <Alert tone="success">
            {t(save.data ? "pwa.reportQueuedSubmit" : "pwa.reportQueued")}
          </Alert>
        ) : null}
        {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
      </ReportForm>
    </div>
  );
}
