import { ApiError, unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, PanelFooter, RuledPanel, SelectField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { CheckField, TextAreaField } from "../layout/PortalPage";

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
    <RuledPanel
      title={t("safeguarding.tutor.loneWorking")}
      titleId="lone-working"
      flush
      footer={
        !visit ? (
          <Button variant="secondary" onClick={() => act.mutate("in")} disabled={act.isPending}>
            {t("safeguarding.tutor.arrived")}
          </Button>
        ) : !visit.checked_out_at ? (
          <Button variant="secondary" onClick={() => act.mutate("out")} disabled={act.isPending}>
            {t("safeguarding.tutor.left")}
          </Button>
        ) : undefined
      }
    >
      {visit ? (
        <p role="status" className="px-5 py-2.5 text-sm tabular-nums">
          {visit.checked_out_at
            ? t("safeguarding.tutor.checkedOutAt", {
                time: formatDateTime(visit.checked_out_at, i18n.language),
              })
            : t("safeguarding.tutor.checkedInAt", {
                time: formatDateTime(visit.checked_in_at, i18n.language),
              })}
        </p>
      ) : null}
      {act.error && !(act.error instanceof ApiError && act.error.status === 422) ? (
        <div className="px-5 py-3">
          <Alert tone="danger">{act.error.message}</Alert>
        </div>
      ) : null}
    </RuledPanel>
  );
}

/** Raise a safeguarding concern from a lesson: it goes only to the safeguarding leads. A
 * secondary button that opens the form in place as a ruled panel. */
export function TutorRaiseConcern({
  lessonId,
  studentId,
}: {
  lessonId: string;
  studentId?: string | null;
}) {
  const { t } = useTranslation();
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
    <div className="space-y-3">
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
          aria-label={t("safeguarding.raiseTitle")}
          onSubmit={(e) => {
            e.preventDefault();
            raise.mutate();
          }}
        >
          <RuledPanel
            title={t("safeguarding.raiseTitle")}
            description={t("safeguarding.raiseHint")}
            flush
          >
            <div className="space-y-3 px-5 py-4">
              <SelectField
                label={t("safeguarding.category")}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                options={CATEGORIES.map((c) => ({
                  value: c,
                  label: t(`safeguarding.categories.${c}`),
                }))}
              />
              <TextAreaField
                label={t("safeguarding.description")}
                required
                rows={6}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
              <CheckField
                label={t("safeguarding.immediateRiskQuestion")}
                checked={risk}
                onChange={(e) => setRisk(e.target.checked)}
              />
              {risk ? <Alert tone="warning">{t("safeguarding.emergency")}</Alert> : null}
              {raise.error ? <Alert tone="danger">{raise.error.message}</Alert> : null}
            </div>
            <PanelFooter>
              <Button type="submit" disabled={raise.isPending}>
                {t("safeguarding.raiseSubmit")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="text-muted-foreground hover:text-foreground"
                onClick={() => setOpen(false)}
              >
                {t("common.cancel")}
              </Button>
            </PanelFooter>
          </RuledPanel>
        </form>
      )}
    </div>
  );
}
