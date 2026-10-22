import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  NamePlate,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { PanelEmpty, PortalHeader, SavedNote } from "../layout/PortalPage";
import { PayDetailsSection } from "./PayPages";
import { PublicProfileSection } from "./PublicProfile";
import { useIsPhone } from "../layout/useIsPhone";
import { useTutorMe } from "./useTutorMe";

const quiet = "text-muted-foreground hover:text-foreground";

/** Students on my active jobs, with their next lesson (E16-T04): name plates in one panel. */
export function StudentsPage() {
  const { t, i18n } = useTranslation();
  const students = useQuery({
    queryKey: ["tutor", "students"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/students")),
  });
  if (students.isPending) return <Spinner label={t("grid.loading")} />;
  return (
    <div>
      <PortalHeader title={t("tutor.nav.students")} />
      <RuledPanel label={t("tutor.nav.students")} flush>
        {students.data?.length ? (
          <PanelRows>
            {students.data.map((st) => (
              <PanelRow key={st.id}>
                <NamePlate
                  name={
                    <Link
                      to="/tutor/students/$studentId"
                      params={{ studentId: st.id }}
                      className="underline-offset-2 hover:underline"
                    >
                      {st.name}
                    </Link>
                  }
                  context={
                    <span className="tabular-nums">
                      {[
                        st.year_group,
                        st.jobs.join(", "),
                        st.next_lesson
                          ? t("tutor.nextLesson", {
                              when: formatDateTime(st.next_lesson, i18n.language),
                            })
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  }
                />
              </PanelRow>
            ))}
          </PanelRows>
        ) : (
          <PanelEmpty>{t("tutor.noStudents")}</PanelEmpty>
        )}
      </RuledPanel>
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
  const { t, i18n } = useTranslation();
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
  const phone = useIsPhone();
  const dayName = (d: number, width: "long" | "short") =>
    new Date(2024, 0, 1 + d).toLocaleDateString(i18n.language, { weekday: width });
  if (availability.isPending) return <Spinner label={t("grid.loading")} />;
  return (
    <div>
      <PortalHeader title={t("tutor.nav.availability")} />
      <div className="space-y-6">
        <form
          aria-label={t("tutor.weekly")}
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <RuledPanel title={t("tutor.weekly")} flush>
            {current.length ? (
              <ul className="divide-y divide-rule">
                {current.map((w, i) => (
                  // One compact row per weekly time: day, from, to, then Remove at the end.
                  // Labels show on the first row only; later rows keep them for screen readers.
                  <li
                    key={i}
                    className="grid grid-cols-[4.75rem_minmax(0,1fr)_minmax(0,1fr)_2rem] items-end gap-x-2 px-5 py-2 sm:grid-cols-[minmax(0,1fr)_8rem_8rem_auto] sm:gap-x-3"
                  >
                    <SelectField
                      size="sm"
                      hideLabel={i > 0}
                      label={t("tutor.day")}
                      value={String(w.weekday)}
                      onChange={(e) =>
                        setWindows(
                          current.map((x, n) =>
                            n === i ? { ...x, weekday: Number(e.target.value) } : x,
                          ),
                        )
                      }
                      options={DAYS.map((d) => ({
                        value: String(d),
                        label: dayName(d, phone ? "short" : "long"),
                      }))}
                    />
                    <TextField
                      size="sm"
                      className="min-w-0 px-2 tabular-nums max-sm:[&::-webkit-calendar-picker-indicator]:hidden"
                      type="time"
                      hideLabel={i > 0}
                      label={t("tutor.from")}
                      value={w.start_time.slice(0, 5)}
                      onChange={(e) =>
                        setWindows(
                          current.map((x, n) =>
                            n === i ? { ...x, start_time: e.target.value } : x,
                          ),
                        )
                      }
                    />
                    <TextField
                      size="sm"
                      className="min-w-0 px-2 tabular-nums max-sm:[&::-webkit-calendar-picker-indicator]:hidden"
                      type="time"
                      hideLabel={i > 0}
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
                      size="sm"
                      variant="ghost"
                      className={`${quiet} w-8 px-0 sm:w-auto sm:px-3`}
                      onClick={() => setWindows(current.filter((_x, n) => n !== i))}
                    >
                      <X aria-hidden="true" className="size-4 sm:hidden" strokeWidth={1.75} />
                      <span className="max-sm:sr-only">{t("tutor.remove")}</span>
                      <span className="sr-only">
                        {" "}
                        {dayName(w.weekday, "long")} {w.start_time.slice(0, 5)}
                      </span>
                    </Button>
                  </li>
                ))}
              </ul>
            ) : (
              <PanelEmpty>{t("designS10.noAvailability")}</PanelEmpty>
            )}
            {save.error ? (
              <div className="px-5 pb-4">
                <Alert tone="danger">{save.error.message}</Alert>
              </div>
            ) : null}
            <PanelFooter>
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
              <SavedNote show={save.isSuccess} />
            </PanelFooter>
          </RuledPanel>
        </form>
        <form
          aria-label={t("tutor.timeOff")}
          onSubmit={(e) => {
            e.preventDefault();
            timeOff.mutate();
          }}
        >
          <RuledPanel title={t("tutor.timeOff")} flush>
            <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-3">
              <TextField
                type="date"
                className="tabular-nums"
                required
                label={t("tutor.firstDay")}
                value={off.start}
                onChange={(e) => setOff({ ...off, start: e.target.value })}
              />
              <TextField
                type="date"
                className="tabular-nums"
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
            {timeOff.error ? (
              <div className="px-5 pb-4">
                <Alert tone="danger">{timeOff.error.message}</Alert>
              </div>
            ) : null}
            <PanelFooter>
              <Button type="submit" variant="secondary" disabled={timeOff.isPending}>
                {t("tutor.addTimeOff")}
              </Button>
              <span role="status" className="text-sm text-success">
                {timeOff.isSuccess ? t("tutor.timeOffAdded") : ""}
              </span>
            </PanelFooter>
          </RuledPanel>
        </form>
      </div>
    </div>
  );
}

/** Public profile basics (E16-T07). Compliance uploads come with E18. */
export function TutorProfilePage() {
  const { t } = useTranslation();
  const me = useTutorMe();
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
  if (profile.isPending) return <Spinner label={t("grid.loading")} />;
  return (
    <div>
      <PortalHeader title={t("tutor.nav.profile")} />
      <div className="space-y-6">
        <form
          aria-label={t("tutor.nav.profile")}
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <RuledPanel title={t("designS10.aboutYou")} flush>
            <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
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
              <div className="sm:col-span-2">
                <TextAreaField
                  label={t("tutor.bio")}
                  rows={5}
                  value={value.bio_public}
                  onChange={(e) => setForm({ ...value, bio_public: e.target.value })}
                />
              </div>
            </div>
            {save.error ? (
              <div className="px-5 pb-4">
                <Alert tone="danger">{save.error.message}</Alert>
              </div>
            ) : null}
            <PanelFooter>
              <Button type="submit" disabled={save.isPending}>
                {t("portal.save")}
              </Button>
              <SavedNote show={save.isSuccess} />
            </PanelFooter>
          </RuledPanel>
        </form>
        <PublicProfileSection />
        <PayDetailsSection />
      </div>
    </div>
  );
}
