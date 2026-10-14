import { ApiError, unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";

const CATEGORIES = [
  "physical", "emotional", "sexual", "neglect", "online", "self_harm", "bullying",
  "radicalisation", "allegation", "conduct", "other",
] as const; // prettier-ignore

/** Lone working (E29-T09): "I've arrived" / "I've left" for in-person lessons. Hidden when
 * the organisation hasn't switched check-ins on or the lesson doesn't need one. */
export function CheckInButtons({ lessonId, online }: { lessonId: string; online: boolean }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const visits = useQuery({
    queryKey: ["tutor", "visits", lessonId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/lone-working/visits", { params: { query: { lesson: lessonId } } }),
      ),
    enabled: !online,
  });
  const visit = visits.data?.results[0];
  const act = useMutation({
    mutationFn: async (kind: "in" | "out") =>
      unwrap(
        await api.POST(
          kind === "in"
            ? "/api/v1/lone-working/visits/check-in"
            : "/api/v1/lone-working/visits/check-out",
          { body: { lesson: lessonId } },
        ),
      ),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["tutor", "visits", lessonId] }),
  });
  if (online) return null;
  // 422: check-ins aren't used for this lesson; don't nag.
  if (act.error instanceof ApiError && act.error.status === 422 && !visit) {
    return <p className="text-sm text-muted-foreground">{act.error.message}</p>;
  }
  return (
    <div
      role="group"
      aria-labelledby="lone-working"
      className="space-y-2 rounded-md border border-border p-3"
    >
      <h2 id="lone-working" className="font-semibold">
        {t("safeguarding.tutor.loneWorking")}
      </h2>
      {visit ? (
        <p role="status" className="text-sm">
          {visit.checked_out_at
            ? t("safeguarding.tutor.checkedOutAt", {
                time: formatDateTime(visit.checked_out_at, i18n.language),
              })
            : t("safeguarding.tutor.checkedInAt", {
                time: formatDateTime(visit.checked_in_at, i18n.language),
              })}
        </p>
      ) : null}
      {!visit ? (
        <Button onClick={() => act.mutate("in")} disabled={act.isPending}>
          {t("safeguarding.tutor.arrived")}
        </Button>
      ) : !visit.checked_out_at ? (
        <Button onClick={() => act.mutate("out")} disabled={act.isPending}>
          {t("safeguarding.tutor.left")}
        </Button>
      ) : null}
      {act.error && !(act.error instanceof ApiError && act.error.status === 422) ? (
        <Alert tone="danger">{act.error.message}</Alert>
      ) : null}
    </div>
  );
}

/** Raise a safeguarding concern from a lesson: it goes only to the safeguarding leads. */
export function TutorRaiseConcern({
  lessonId,
  studentId,
}: {
  lessonId: string;
  studentId?: string | null;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState("other");
  const [description, setDescription] = useState("");
  const [risk, setRisk] = useState(false);
  const raise = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/safeguarding/concerns", {
          body: {
            category: category as "other",
            description,
            immediate_risk: risk,
            lesson: lessonId,
            ...(studentId ? { student: studentId } : {}),
          },
        }),
      ),
    onSuccess: () => {
      setDescription("");
      setOpen(false);
    },
  });
  return (
    <div role="group" aria-labelledby={`${id}-title`} className="space-y-2">
      <h2 id={`${id}-title`} className="sr-only">
        {t("safeguarding.raiseTitle")}
      </h2>
      {raise.isSuccess ? (
        <Alert tone="success">
          {t("safeguarding.raised", { reference: raise.data.reference })}
        </Alert>
      ) : null}
      {!open ? (
        <Button variant="secondary" onClick={() => setOpen(true)}>
          {t("safeguarding.raiseButton")}
        </Button>
      ) : (
        <form
          className="space-y-3 rounded-md border border-border p-3"
          aria-label={t("safeguarding.raiseTitle")}
          onSubmit={(e) => {
            e.preventDefault();
            raise.mutate();
          }}
        >
          <p className="text-sm text-muted-foreground">{t("safeguarding.raiseHint")}</p>
          <SelectField
            label={t("safeguarding.category")}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            options={CATEGORIES.map((c) => ({
              value: c,
              label: t(`safeguarding.categories.${c}`),
            }))}
          />
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-description`} className="text-sm font-medium">
              {t("safeguarding.description")}
            </label>
            <textarea
              id={`${id}-description`}
              required
              rows={6}
              className="rounded-md border border-border bg-background p-2 text-sm"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={risk} onChange={(e) => setRisk(e.target.checked)} />
            {t("safeguarding.immediateRiskQuestion")}
          </label>
          {risk ? <Alert tone="warning">{t("safeguarding.emergency")}</Alert> : null}
          {raise.error ? <Alert tone="danger">{raise.error.message}</Alert> : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={raise.isPending}>
              {t("safeguarding.raiseSubmit")}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              {t("common.cancel")}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
