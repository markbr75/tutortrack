import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, useMe, usePermission } from "../api";
import { fromInputs, toDateInput, viewerTimeZone } from "./dates";
import { ErrorList } from "./ErrorList";

type Window = components["schemas"]["Window"];
type Mode = components["schemas"]["WindowModeEnum"];

const EMPTY_WINDOW: Window = { weekday: 0, start_time: "16:00", end_time: "19:00", mode: "any" };

function WeeklyWindows({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const current = useQuery({
    queryKey: ["availability", tutorId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/availability/{tutor_id}", {
          params: { path: { tutor_id: tutorId } },
        }),
      ),
  });
  const [windows, setWindows] = useState<Window[]>([]);
  const [from, setFrom] = useState(toDateInput(new Date()));
  useEffect(() => {
    if (current.data)
      setWindows(
        current.data.windows.map((w) => ({
          ...w,
          start_time: w.start_time.slice(0, 5),
          end_time: w.end_time.slice(0, 5),
        })),
      );
  }, [current.data]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/availability/{tutor_id}", {
          params: { path: { tutor_id: tutorId } },
          body: {
            effective_from: from,
            timezone: current.data?.timezone || viewerTimeZone(),
            windows,
          },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["availability", tutorId] }),
  });
  const update = (index: number, patch: Partial<Window>) =>
    setWindows((list) => list.map((w, i) => (i === index ? { ...w, ...patch } : w)));
  if (current.isPending) return <Spinner label={t("grid.loading")} />;
  return (
    <section className="rounded-lg border border-border p-4">
      <h2 className="mb-3 font-semibold">{t("availability.weekly")}</h2>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        {windows.map((w, index) => (
          <fieldset
            key={index}
            className="grid grid-cols-2 gap-2 sm:grid-cols-[10rem_7rem_7rem_12rem_auto] sm:items-end"
          >
            <legend className="sr-only">{t("availability.window", { n: index + 1 })}</legend>
            <SelectField
              label={t("availability.day")}
              value={String(w.weekday)}
              onChange={(e) => update(index, { weekday: Number(e.target.value) })}
              options={[0, 1, 2, 3, 4, 5, 6].map((d) => ({
                value: String(d),
                label: t(`jobs.weekday.${d}`),
              }))}
            />
            <TextField
              label={t("calendar.from")}
              type="time"
              step={300}
              value={w.start_time}
              onChange={(e) => update(index, { start_time: e.target.value })}
            />
            <TextField
              label={t("calendar.to")}
              type="time"
              step={300}
              value={w.end_time}
              onChange={(e) => update(index, { end_time: e.target.value })}
            />
            <SelectField
              label={t("availability.mode")}
              value={w.mode ?? "any"}
              onChange={(e) => update(index, { mode: e.target.value as Mode })}
              options={(["any", "in_person", "online"] as const).map((m) => ({
                value: m,
                label: t(`availability.modes.${m}`),
              }))}
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={t("availability.removeWindow", { n: index + 1 })}
              onClick={() => setWindows((list) => list.filter((_, i) => i !== index))}
            >
              {t("availability.remove")}
            </Button>
          </fieldset>
        ))}
        {windows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("availability.none")}</p>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => setWindows((list) => [...list, { ...EMPTY_WINDOW }])}
        >
          {t("availability.addWindow")}
        </Button>
        <div className="flex flex-wrap items-end gap-2">
          <TextField
            label={t("availability.from")}
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
          <Button type="submit" disabled={save.isPending}>
            {t("availability.save")}
          </Button>
        </div>
        {save.isSuccess ? (
          <p role="status" className="text-sm">
            {t("availability.saved")}
          </p>
        ) : null}
        <ErrorList error={save.error} />
      </form>
    </section>
  );
}

function TimeOff({ tutorId }: { tutorId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    type: "off" as "off" | "extra",
    start: toDateInput(new Date()),
    end: toDateInput(new Date()),
    reason: "",
  });
  const [clashes, setClashes] = useState<number | null>(null);
  const list = useQuery({
    queryKey: ["time-off", tutorId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/time-off", { params: { query: { tutor: tutorId } } })),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["time-off", tutorId] });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/time-off", {
          body: {
            tutor: tutorId,
            type: form.type,
            start: fromInputs(form.start, "00:00").toISOString(),
            end: fromInputs(form.end, "23:59").toISOString(),
            reason: form.reason,
          },
        }),
      ),
    onSuccess: (body) => {
      setClashes(((body as unknown as { clashes?: string[] }).clashes ?? []).length);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/time-off/{id}", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  return (
    <section className="rounded-lg border border-border p-4">
      <h2 className="mb-3 font-semibold">{t("availability.timeOff")}</h2>
      <ul className="mb-3 space-y-1 text-sm">
        {(list.data?.results ?? []).map((x) => (
          <li key={x.id} className="flex flex-wrap items-center gap-2">
            <span>
              {t(`availability.types.${x.type}`)}: {formatDateTime(x.start, i18n.language)} –{" "}
              {formatDateTime(x.end, i18n.language)}
              {x.reason ? ` (${x.reason})` : ""}
            </span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => remove.mutate(x.id)}
              aria-label={t("availability.removeEntry")}
            >
              {t("availability.remove")}
            </Button>
          </li>
        ))}
      </ul>
      <form
        className="grid gap-2 sm:grid-cols-[10rem_10rem_10rem_1fr_auto] sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <SelectField
          label={t("availability.type")}
          value={form.type}
          onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as "off" | "extra" }))}
          options={(["off", "extra"] as const).map((v) => ({
            value: v,
            label: t(`availability.types.${v}`),
          }))}
        />
        <TextField
          label={t("availability.firstDay")}
          type="date"
          value={form.start}
          onChange={(e) => setForm((f) => ({ ...f, start: e.target.value }))}
        />
        <TextField
          label={t("availability.lastDay")}
          type="date"
          value={form.end}
          onChange={(e) => setForm((f) => ({ ...f, end: e.target.value }))}
        />
        <TextField
          label={t("calendar.reason")}
          value={form.reason}
          onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
        />
        <Button type="submit" disabled={add.isPending}>
          {t("availability.add")}
        </Button>
      </form>
      {clashes ? (
        <p role="status" className="mt-2 text-sm">
          {t("availability.clashes", { count: clashes })}
        </p>
      ) : null}
      <ErrorList error={add.error} />
    </section>
  );
}

function CalendarFeed({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState("");
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/ical-feeds", { body: { kind: "tutor", subject_id: tutorId } }),
      ),
    onSuccess: (feed) => setUrl((feed as unknown as { url: string }).url),
  });
  return (
    <section className="rounded-lg border border-border p-4">
      <h2 className="mb-2 font-semibold">{t("availability.feed")}</h2>
      <p className="mb-3 text-sm text-muted-foreground">{t("availability.feedHelp")}</p>
      {url ? (
        <TextField
          label={t("availability.feedUrl")}
          readOnly
          value={url}
          onFocus={(e) => e.currentTarget.select()}
        />
      ) : (
        <Button variant="secondary" onClick={() => create.mutate()} disabled={create.isPending}>
          {t("availability.createFeed")}
        </Button>
      )}
      <ErrorList error={create.error} />
    </section>
  );
}

/** Availability, time off and the calendar feed (FR-08-5, FR-08-11). Tutors edit their
 * own; managers pick a tutor. */
export function AvailabilityPage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const canManage = usePermission("scheduling.availability.manage_others");
  const tutors = useQuery({
    queryKey: ["tutors", "availability"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active", "onboarding"], page_size: 200 } },
        }),
      ),
  });
  const list = tutors.data?.results ?? [];
  const own = list.find((p) => p.email === me?.user.email);
  const [chosen, setChosen] = useState("");
  const tutorId = chosen || own?.id || (canManage ? list[0]?.id : undefined) || "";
  return (
    <section className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">{t("availability.title")}</h1>
      {canManage && list.length ? (
        <SelectField
          label={t("calendar.tutor")}
          value={tutorId}
          onChange={(e) => setChosen(e.target.value)}
          options={list.map((p) => ({ value: p.id, label: p.full_name }))}
        />
      ) : null}
      {tutorId ? (
        <>
          <WeeklyWindows key={`w-${tutorId}`} tutorId={tutorId} />
          <TimeOff key={`t-${tutorId}`} tutorId={tutorId} />
          <CalendarFeed key={`f-${tutorId}`} tutorId={tutorId} />
        </>
      ) : (
        <p className="text-sm text-muted-foreground">{t("availability.noTutor")}</p>
      )}
    </section>
  );
}
