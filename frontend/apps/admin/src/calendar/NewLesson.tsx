import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, usePermission } from "../api";
import { fromInputs, toDateInput, toTimeInput } from "./dates";
import { ErrorList } from "./QuickView";
import { conflictsOf } from "./types";

const WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"] as const;

interface Draft {
  service: string;
  tutor: string;
  students: string[];
  date: string;
  time: string;
  duration: string;
  repeat: boolean;
  days: string[];
  ends: "count" | "until";
  count: string;
  until: string;
}

/** Schedule a lesson or a weekly series (FR-08-1, FR-08-2). */
export function NewLesson({
  start,
  tutorId,
  onClose,
}: {
  start: Date | null;
  tutorId?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDialogElement>(null);
  const canOverride = usePermission("scheduling.override_conflicts");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [created, setCreated] = useState<{ count: number; skipped: number } | null>(null);
  const set = (patch: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...patch } : d));

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (start) {
      const weekday = WEEKDAY_CODES[(start.getDay() + 6) % 7] ?? "MO";
      setDraft({
        service: "",
        tutor: tutorId ?? "",
        students: [""],
        date: toDateInput(start),
        time: toTimeInput(start),
        duration: "60",
        repeat: false,
        days: [weekday],
        ends: "count",
        count: "10",
        until: "",
      });
      setCreated(null);
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [start, tutorId]);

  const services = useQuery({
    queryKey: ["catalogue", "services", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/catalogue/services", {
          params: { query: { active: true, page_size: 200 } },
        }),
      ),
    enabled: Boolean(start),
  });
  const tutors = useQuery({
    queryKey: ["tutors", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active"], page_size: 200 } },
        }),
      ),
    enabled: Boolean(start),
  });
  const students = useQuery({
    queryKey: ["students", "schedulable"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/students", {
          params: { query: { status: ["active", "trial"], page_size: 200 } },
        }),
      ),
    enabled: Boolean(start),
  });

  const save = useMutation({
    mutationFn: async (override: boolean) => {
      const d = draft!;
      const attendees = d.students.filter(Boolean).map((student) => ({ student }));
      const tutorsIn = d.tutor ? [{ tutor: d.tutor }] : [];
      if (!d.repeat) {
        const startAt = fromInputs(d.date, d.time);
        const end = new Date(startAt.getTime() + Number(d.duration) * 60_000);
        return unwrap(
          await api.POST("/api/v1/lessons", {
            body: {
              service: d.service,
              start: startAt.toISOString(),
              end: end.toISOString(),
              attendees,
              tutors: tutorsIn,
              override_conflicts: override,
            },
          }),
        ).lesson
          ? { count: 1, skipped: 0 }
          : { count: 0, skipped: 0 };
      }
      const result = unwrap(
        await api.POST("/api/v1/lesson-series", {
          body: {
            service: d.service,
            rrule: `FREQ=WEEKLY;BYDAY=${d.days.join(",")}`,
            start_date: d.date,
            start_time: d.time,
            duration_minutes: Number(d.duration),
            count: d.ends === "count" ? Number(d.count) : null,
            until: d.ends === "until" && d.until ? d.until : null,
            attendees,
            tutors: tutorsIn,
            skip_holidays: true,
            online: false,
            notes_for_tutor: "",
            conflict_mode: override ? "create" : "skip",
          },
        }),
      );
      return { count: result.lessons_created, skipped: result.skipped.length };
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["calendar"] });
      if (result.skipped) setCreated(result);
      else onClose();
    },
  });

  const d = draft;
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="new-lesson-title"
      className="w-full max-w-lg rounded-lg border border-border bg-background p-5 shadow-lg backdrop:bg-black/40"
    >
      {d ? (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(false);
          }}
        >
          <h2 id="new-lesson-title" className="text-lg font-semibold">
            {t("calendar.new.title")}
          </h2>
          <SelectField
            label={t("calendar.new.service")}
            required
            value={d.service}
            onChange={(e) => set({ service: e.target.value })}
            options={[
              { value: "", label: t("catalogue.price.choose") },
              ...(services.data?.results ?? []).map((s) => ({ value: s.id, label: s.name })),
            ]}
          />
          <SelectField
            label={t("calendar.new.tutor")}
            value={d.tutor}
            onChange={(e) => set({ tutor: e.target.value })}
            options={[
              { value: "", label: t("calendar.new.noTutor") },
              ...(tutors.data?.results ?? []).map((p) => ({ value: p.id, label: p.full_name })),
            ]}
          />
          {d.students.map((value, index) => (
            <SelectField
              key={index}
              label={t("calendar.new.student", { n: index + 1 })}
              required={index === 0}
              value={value}
              onChange={(e) =>
                set({ students: d.students.map((s, i) => (i === index ? e.target.value : s)) })
              }
              options={[
                { value: "", label: t("calendar.new.chooseStudent") },
                ...(students.data?.results ?? []).map((s) => ({ value: s.id, label: s.full_name })),
              ]}
            />
          ))}
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => set({ students: [...d.students, ""] })}
          >
            {t("calendar.new.addStudent")}
          </Button>
          <div className="grid grid-cols-3 gap-2">
            <TextField
              label={t("calendar.date")}
              type="date"
              required
              value={d.date}
              onChange={(e) => set({ date: e.target.value })}
            />
            <TextField
              label={t("calendar.from")}
              type="time"
              step={300}
              required
              value={d.time}
              onChange={(e) => set({ time: e.target.value })}
            />
            <TextField
              label={t("calendar.new.minutes")}
              type="number"
              min={5}
              max={720}
              step={5}
              required
              value={d.duration}
              onChange={(e) => set({ duration: e.target.value })}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={d.repeat}
              onChange={(e) => set({ repeat: e.target.checked })}
            />
            {t("calendar.new.repeat")}
          </label>
          {d.repeat ? (
            <fieldset className="space-y-2 rounded-md border border-border p-3">
              <legend className="px-1 text-sm font-medium">{t("calendar.new.on")}</legend>
              <div className="flex flex-wrap gap-3">
                {WEEKDAY_CODES.map((code, i) => (
                  <label key={code} className="flex items-center gap-1 text-sm">
                    <input
                      type="checkbox"
                      className="size-4"
                      checked={d.days.includes(code)}
                      onChange={(e) =>
                        set({
                          days: e.target.checked
                            ? WEEKDAY_CODES.filter((c) => c === code || d.days.includes(c))
                            : d.days.filter((c) => c !== code),
                        })
                      }
                    />
                    {t(`jobs.weekday.${i}`)}
                  </label>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <SelectField
                  label={t("calendar.new.ends")}
                  value={d.ends}
                  onChange={(e) => set({ ends: e.target.value as Draft["ends"] })}
                  options={[
                    { value: "count", label: t("calendar.new.afterCount") },
                    { value: "until", label: t("calendar.new.onDate") },
                  ]}
                />
                {d.ends === "count" ? (
                  <TextField
                    label={t("calendar.new.lessons")}
                    type="number"
                    min={1}
                    max={520}
                    value={d.count}
                    onChange={(e) => set({ count: e.target.value })}
                  />
                ) : (
                  <TextField
                    label={t("calendar.new.lastDate")}
                    type="date"
                    value={d.until}
                    onChange={(e) => set({ until: e.target.value })}
                  />
                )}
              </div>
            </fieldset>
          ) : null}
          <ErrorList error={save.error} />
          {created ? (
            <p role="status" className="text-sm">
              {t("calendar.new.createdSkipped", { count: created.count, skipped: created.skipped })}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              disabled={
                save.isPending || !d.service || !d.students[0] || (d.repeat && !d.days.length)
              }
            >
              {d.repeat ? t("calendar.new.saveSeries") : t("calendar.new.save")}
            </Button>
            {conflictsOf(save.error).length && canOverride ? (
              <Button type="button" variant="secondary" onClick={() => save.mutate(true)}>
                {t("calendar.scheduleAnyway")}
              </Button>
            ) : null}
            <Button type="button" variant="ghost" onClick={onClose}>
              {created ? t("calendar.close") : t("catalogue.cancel")}
            </Button>
          </div>
        </form>
      ) : null}
    </dialog>
  );
}
