import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";

type VideoAttendance = components["schemas"]["VideoAttendance"];
const TIN_TYPES = ["ssn", "itin", "ein"] as const;

/** The register suggested by who joined the online lesson (E22-T10); applying it fills in
 * the tutor's register, which they still confirm. */
export function VideoRegisterHint({
  lessonId,
  onApply,
}: {
  lessonId: string;
  onApply: (suggestion: VideoAttendance) => void;
}) {
  const { t } = useTranslation();
  const data = useQuery({
    queryKey: ["tutor", "lesson", lessonId, "video-attendance"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/lessons/{id}/video-attendance", {
        params: { path: { id: lessonId } },
      });
      return data ?? null;
    },
  });
  if (!data.data?.available) return null;
  return (
    <div className="space-y-1 rounded-md border border-border p-3 text-sm" role="note">
      <p>{t("videoLessons.fromVideo")}</p>
      {data.data.actual_minutes !== null ? (
        <p>{t("videoLessons.actualMinutes", { count: data.data.actual_minutes })}</p>
      ) : null}
      <Button size="sm" variant="secondary" type="button" onClick={() => onApply(data.data!)}>
        {t("videoLessons.useSuggestion")}
      </Button>
    </div>
  );
}

/** Link to the in-app classroom for online lessons (FR-22-5). */
export function ClassroomLink({ lessonId }: { lessonId: string }) {
  const { t } = useTranslation();
  return (
    <p>
      <Link to="/classroom/$lessonId" params={{ lessonId }} className="text-sm underline">
        {t("classroom.open")}
      </Link>
    </p>
  );
}

/** The tutor's recordings of this lesson (released ones only). */
export function TutorRecordings({ lessonId }: { lessonId: string }) {
  const { t, i18n } = useTranslation();
  const recordings = useQuery({
    queryKey: ["tutor", "lesson", lessonId, "recordings"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/recordings", {
        params: { query: { lesson: lessonId } },
      });
      return data?.results ?? [];
    },
  });
  const play = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.GET("/api/v1/recordings/{id}/play", { params: { path: { id } } })),
    onSuccess: (link) => window.open(link.url, "_blank", "noopener"),
  });
  if (!recordings.data?.length) return null;
  return (
    <section aria-labelledby="lesson-recordings" className="space-y-1 text-sm">
      <h2 id="lesson-recordings" className="font-semibold">
        {t("videoLessons.recordings")}
      </h2>
      <ul className="space-y-1">
        {recordings.data.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-2">
            <span>
              {r.started_at
                ? formatDateTime(r.started_at, i18n.language)
                : t("videoLessons.recording")}
            </span>
            <Button size="sm" variant="secondary" onClick={() => play.mutate(r.id)}>
              {t("videoLessons.watch")}
            </Button>
          </li>
        ))}
      </ul>
      {play.error ? <Alert tone="danger">{play.error.message}</Alert> : null}
    </section>
  );
}

/** The tutor's online background checks with the link to complete each (E18-T11). */
export function MyBackgroundChecks() {
  const { t } = useTranslation();
  const checks = useQuery({
    queryKey: ["tutor", "background-checks"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/me/background-checks");
      return data ?? [];
    },
  });
  if (!checks.data?.length) return null;
  return (
    <section aria-labelledby="my-checks" className="space-y-2">
      <h2 id="my-checks" className="font-semibold">
        {t("backgroundChecks.mine")}
      </h2>
      <ul className="space-y-2 text-sm">
        {checks.data.map((c) => (
          <li key={c.id} className="space-y-1 rounded-lg border border-border p-3">
            <p className="font-medium">
              {c.provider_label}: {t(`backgroundChecks.status.${c.status}`)}
            </p>
            {c.invite_url ? (
              <p>
                <a className="underline" href={c.invite_url} target="_blank" rel="noreferrer">
                  {t("backgroundChecks.complete")}
                </a>
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** US tax information for 1099-NEC (E12-T12): the tutor's taxpayer id (shown masked) and
 * what they were paid last tax year. Shown to tutors paid in US dollars. */
export function MyUsTaxInfo() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const year = new Date().getFullYear() - 1;
  const profile = useQuery({
    queryKey: ["tutor", "pay-profile"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/me/pay-profile");
      return data ?? null;
    },
  });
  const identity = useQuery({
    queryKey: ["tutor", "tax-identity"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/me/tax-identity");
      return data ?? null;
    },
  });
  const summary = useQuery({
    queryKey: ["tutor", "tax-summary", year],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/me/tax-summary", { params: { query: { year } } });
      return data ?? null;
    },
  });
  const [tinType, setTinType] = useState<(typeof TIN_TYPES)[number]>("ssn");
  const [tin, setTin] = useState("");
  const save = useMutation({
    mutationFn: async () =>
      unwrap(await api.PUT("/api/v1/me/tax-identity", { body: { tin_type: tinType, tin } })),
    onSuccess: (data) => {
      setTin("");
      queryClient.setQueryData(["tutor", "tax-identity"], data);
    },
  });
  const usd =
    profile.data?.currency === "USD" ||
    Boolean(identity.data?.tin_hint) ||
    (summary.data ? summary.data.box1 !== "0.00" : false);
  if (!usd) return null;
  return (
    <section
      aria-labelledby="us-tax"
      className="space-y-2 rounded-lg border border-border p-3 text-sm"
    >
      <h2 id="us-tax" className="font-semibold">
        {t("payrollPhase3.usTaxTitle")}
      </h2>
      {summary.data ? (
        <p>
          {t("payrollPhase3.paidInYear", {
            year,
            amount: formatMoney(
              { amount: summary.data.box1, currency: summary.data.currency },
              i18n.language,
            ),
          })}
          {summary.data.filed ? ` ${t("payrollPhase3.formFiled")}` : ""}
        </p>
      ) : null}
      <p>
        {identity.data?.tin_hint
          ? t("payrollPhase3.yourTaxIdOnFile", { hint: identity.data.tin_hint })
          : t("payrollPhase3.addYourTaxId")}
      </p>
      <form
        className="grid gap-2 sm:grid-cols-[auto_1fr_auto] sm:items-end"
        aria-label={t("payrollPhase3.taxId")}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <SelectField
          label={t("payrollPhase3.tinType")}
          value={tinType}
          options={TIN_TYPES.map((v) => ({ value: v, label: t(`payrollPhase3.tinTypes.${v}`) }))}
          onChange={(e) => setTinType(e.target.value as (typeof TIN_TYPES)[number])}
        />
        <TextField
          label={t("payrollPhase3.tin")}
          autoComplete="off"
          inputMode="numeric"
          value={tin}
          onChange={(e) => setTin(e.target.value)}
        />
        <Button type="submit" size="sm" disabled={!tin} loading={save.isPending}>
          {t("payrollPhase3.saveTaxId")}
        </Button>
      </form>
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </section>
  );
}
