import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";
import { PayDetailsSection } from "./PayPages";
import { useTutorMe } from "./useTutorMe";

/** Students on my active jobs, with their next lesson (E16-T04). */
export function StudentsPage() {
  const { t, i18n } = useTranslation();
  const students = useQuery({
    queryKey: ["tutor", "students"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/students")),
  });
  if (students.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">{t("tutor.nav.students")}</h1>
      {!students.data?.length ? (
        <p className="text-sm text-muted-foreground">{t("tutor.noStudents")}</p>
      ) : null}
      <ul className="space-y-2">
        {students.data?.map((st) => (
          <li key={st.id} className="rounded-lg border border-border p-3">
            <p className="font-medium">{st.name}</p>
            <p className="text-sm text-muted-foreground">
              {[st.year_group, st.jobs.join(", ")].filter(Boolean).join(" · ")}
            </p>
            {st.next_lesson ? (
              <p className="text-sm">
                {t("tutor.nextLesson", { when: formatDateTime(st.next_lesson, i18n.language) })}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

const DAYS = [0, 1, 2, 3, 4, 5, 6];
interface Window {
  weekday: number;
  start_time: string;
  end_time: string;
  mode: "any" | "in_person" | "online";
}

/** Weekly availability and time off (E16-T05). */
export function AvailabilityPage() {
  const { t } = useTranslation();
  const me = useTutorMe();
  const queryClient = useQueryClient();
  const tutorId = me.data?.id ?? "";
  const availability = useQuery({
    queryKey: ["tutor", "availability", tutorId],
    enabled: Boolean(tutorId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/availability/{tutor_id}", {
          params: { path: { tutor_id: tutorId } },
        }),
      ),
  });
  const [windows, setWindows] = useState<Window[] | null>(null);
  const current: Window[] = windows ?? ((availability.data?.windows ?? []) as Window[]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/availability/{tutor_id}", {
          params: { path: { tutor_id: tutorId } },
          body: {
            effective_from: new Date().toISOString().slice(0, 10),
            timezone:
              availability.data?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
            windows: current,
          },
        }),
      ),
    onSuccess: () => {
      setWindows(null);
      void queryClient.invalidateQueries({ queryKey: ["tutor", "availability"] });
    },
  });
  const [off, setOff] = useState({ start: "", end: "", reason: "" });
  const timeOff = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/time-off", {
          body: {
            tutor: tutorId,
            type: "off",
            start: new Date(`${off.start}T00:00`).toISOString(),
            end: new Date(`${off.end}T23:59`).toISOString(),
            reason: off.reason,
          },
        }),
      ),
    onSuccess: () => setOff({ start: "", end: "", reason: "" }),
  });
  const dayName = (d: number) =>
    new Date(2024, 0, 1 + d).toLocaleDateString(undefined, { weekday: "long" });
  if (availability.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">{t("tutor.nav.availability")}</h1>
      <form
        className="space-y-3"
        aria-label={t("tutor.weekly")}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <h2 className="font-semibold">{t("tutor.weekly")}</h2>
        {current.map((w, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2">
            <SelectField
              label={t("tutor.day")}
              value={String(w.weekday)}
              onChange={(e) =>
                setWindows(
                  current.map((x, n) => (n === i ? { ...x, weekday: Number(e.target.value) } : x)),
                )
              }
              options={DAYS.map((d) => ({ value: String(d), label: dayName(d) }))}
            />
            <TextField
              type="time"
              label={t("tutor.from")}
              value={w.start_time.slice(0, 5)}
              onChange={(e) =>
                setWindows(
                  current.map((x, n) => (n === i ? { ...x, start_time: e.target.value } : x)),
                )
              }
            />
            <TextField
              type="time"
              label={t("tutor.to")}
              value={w.end_time.slice(0, 5)}
              onChange={(e) =>
                setWindows(
                  current.map((x, n) => (n === i ? { ...x, end_time: e.target.value } : x)),
                )
              }
            />
            <Button
              type="button"
              variant="ghost"
              onClick={() => setWindows(current.filter((_x, n) => n !== i))}
            >
              {t("tutor.remove")}
            </Button>
          </div>
        ))}
        <div className="flex gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              setWindows([
                ...current,
                { weekday: 0, start_time: "16:00", end_time: "19:00", mode: "any" },
              ])
            }
          >
            {t("tutor.addTime")}
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {t("tutor.saveAvailability")}
          </Button>
        </div>
        {save.isSuccess ? <Alert tone="success">{t("portal.saved")}</Alert> : null}
        {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
      </form>
      <form
        className="space-y-2"
        aria-label={t("tutor.timeOff")}
        onSubmit={(e) => {
          e.preventDefault();
          timeOff.mutate();
        }}
      >
        <h2 className="font-semibold">{t("tutor.timeOff")}</h2>
        <div className="flex flex-wrap gap-2">
          <TextField
            type="date"
            required
            label={t("tutor.firstDay")}
            value={off.start}
            onChange={(e) => setOff({ ...off, start: e.target.value })}
          />
          <TextField
            type="date"
            required
            label={t("tutor.lastDay")}
            value={off.end}
            onChange={(e) => setOff({ ...off, end: e.target.value })}
          />
          <TextField
            label={t("portal.reason")}
            value={off.reason}
            onChange={(e) => setOff({ ...off, reason: e.target.value })}
          />
        </div>
        <Button type="submit" variant="secondary" disabled={timeOff.isPending}>
          {t("tutor.addTimeOff")}
        </Button>
        {timeOff.isSuccess ? <Alert tone="success">{t("tutor.timeOffAdded")}</Alert> : null}
        {timeOff.error ? <Alert tone="danger">{timeOff.error.message}</Alert> : null}
      </form>
    </div>
  );
}

/** Public profile basics (E16-T07). Compliance uploads come with E18. */
export function TutorProfilePage() {
  const { t } = useTranslation();
  const me = useTutorMe();
  const bioId = useId();
  const tutorId = me.data?.id ?? "";
  const profile = useQuery({
    queryKey: ["tutor", "profile", tutorId],
    enabled: Boolean(tutorId),
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/tutors/{id}", { params: { path: { id: tutorId } } })),
  });
  const [form, setForm] = useState<{ headline: string; bio_public: string; phone: string } | null>(
    null,
  );
  const value = form ?? {
    headline: profile.data?.headline ?? "",
    bio_public: profile.data?.bio_public ?? "",
    phone: profile.data?.phone ?? "",
  };
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/tutors/{id}", {
          params: { path: { id: tutorId } },
          body: { ...value, invite: false },
        }),
      ),
  });
  if (profile.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  return (
    <div className="space-y-8">
      <form
        className="space-y-3"
        aria-label={t("tutor.nav.profile")}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <h1 className="text-xl font-semibold">{t("tutor.nav.profile")}</h1>
        <TextField
          label={t("tutor.headline")}
          value={value.headline}
          onChange={(e) => setForm({ ...value, headline: e.target.value })}
        />
        <TextField
          label={t("portal.phone")}
          value={value.phone}
          onChange={(e) => setForm({ ...value, phone: e.target.value })}
        />
        <div className="space-y-1">
          <label htmlFor={bioId} className="text-sm font-medium">
            {t("tutor.bio")}
          </label>
          <textarea
            id={bioId}
            className="min-h-32 w-full rounded-md border border-border bg-background px-3 py-2"
            value={value.bio_public}
            onChange={(e) => setForm({ ...value, bio_public: e.target.value })}
          />
        </div>
        {save.isSuccess ? <Alert tone="success">{t("portal.saved")}</Alert> : null}
        {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
        <Button type="submit" disabled={save.isPending}>
          {t("portal.save")}
        </Button>
      </form>
      <PayDetailsSection />
    </div>
  );
}
