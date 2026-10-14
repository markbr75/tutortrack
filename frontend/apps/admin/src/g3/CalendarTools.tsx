import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import type { CalendarItem } from "../calendar/types";
import { COMMON_ZONES } from "./zones";

/** The calendar's filters, saved as named sets (FR-08-7 saved filter sets, gap G3). */
export interface CalendarFilters {
  view: string;
  tutor: string;
  status: string;
  colourBy: string;
}

const ENTITY = "calendar";

/** Saved filter sets on the E05 saved views (``entity_type = "calendar"``): pick one to
 * apply it, save the current filters under a name, or delete your own. */
export function SavedFilterSets({
  current,
  onApply,
}: {
  current: CalendarFilters;
  onApply: (filters: CalendarFilters) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState("");
  const sets = useQuery({
    queryKey: ["saved-views", ENTITY],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/saved-views", { params: { query: { entity_type: ENTITY } } })),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["saved-views", ENTITY] });
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/saved-views", {
          body: { entity_type: ENTITY, name, filters: current, shared: false },
        }),
      ),
    onSuccess: (view) => {
      setName("");
      setChosen(view.id);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      api.DELETE("/api/v1/saved-views/{id}", { params: { path: { id } } }),
    onSuccess: () => {
      setChosen("");
      refresh();
    },
  });
  const rows = sets.data ?? [];
  return (
    <fieldset className="flex flex-wrap items-end gap-2">
      <legend className="sr-only">{t("g3.calendar.savedSets")}</legend>
      <SelectField
        label={t("g3.calendar.savedSets")}
        value={chosen}
        onChange={(e) => {
          setChosen(e.target.value);
          const found = rows.find((r) => r.id === e.target.value);
          if (found) onApply(found.filters as CalendarFilters);
        }}
        options={[
          { value: "", label: t("g3.calendar.chooseSet") },
          ...rows.map((r) => ({ value: r.id, label: r.name })),
        ]}
      />
      {chosen ? (
        <Button size="sm" variant="ghost" onClick={() => remove.mutate(chosen)}>
          {t("g3.calendar.deleteSet")}
        </Button>
      ) : null}
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) save.mutate();
        }}
      >
        <TextField
          label={t("g3.calendar.setName")}
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.target.value)}
        />
        <Button size="sm" type="submit" variant="secondary" disabled={!name.trim()}>
          {t("g3.calendar.saveSet")}
        </Button>
      </form>
    </fieldset>
  );
}

export function SecondaryZoneSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (zone: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <SelectField
      label={t("g3.calendar.secondaryZone")}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      options={[
        { value: "", label: t("g3.calendar.noSecondaryZone") },
        ...COMMON_ZONES.map((z) => ({ value: z, label: z.replace("_", " ") })),
      ]}
    />
  );
}

/** Opens the printable PDF timetable (FR-08-7) for the visible range and tutor. */
export function PrintTimetable({ start, end, tutor }: { start: Date; end: Date; tutor: string }) {
  const { t } = useTranslation();
  const days = (end.getTime() - start.getTime()) / 86_400_000;
  const params = new URLSearchParams({
    start: start.toISOString(),
    end: (days > 31 ? new Date(start.getTime() + 31 * 86_400_000) : end).toISOString(),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
  if (tutor) params.set("tutor", tutor);
  return (
    <a
      className="inline-flex h-8 items-center rounded-md border border-border px-3 text-sm"
      href={`/api/v1/calendar/timetable?${params.toString()}`}
      target="_blank"
      rel="noreferrer"
    >
      {t("g3.calendar.print")}
    </a>
  );
}

type BulkAction = "complete" | "cancel" | "reassign_tutor" | "change_location" | "delete";

function csvCell(value: string): string {
  const safe = /^[=+\-@]/.test(value) ? `'${value}` : value;
  return `"${safe.replace(/"/g, '""')}"`;
}

/** Bulk actions on selected lessons (FR-08-10): complete, cancel, reassign the tutor,
 * change the location, delete planned lessons, or export them as CSV. */
export function BulkLessonBar({
  selected,
  items,
  tutors,
  onDone,
}: {
  selected: string[];
  items: CalendarItem[];
  tutors: { id: string; name: string }[];
  onDone: (remaining: string[]) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("scheduling.lesson.edit");
  const [action, setAction] = useState<BulkAction>("complete");
  const [tutor, setTutor] = useState("");
  const [location, setLocation] = useState("");
  const locations = useQuery({
    queryKey: ["catalogue", "locations"],
    enabled: action === "change_location",
    queryFn: async () => unwrap(await api.GET("/api/v1/catalogue/locations")),
  });
  const run = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/lessons/bulk", {
          body: {
            action,
            ids: selected,
            reason: "",
            cancelled_by: "admin",
            ...(action === "reassign_tutor" ? { tutor } : {}),
            ...(action === "change_location" ? { location: location || null } : {}),
          },
        }),
      ),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["calendar"] });
      onDone(Object.keys(result.failed)); // the ones that failed stay selected
    },
  });
  const exportCsv = () => {
    const chosen = items.filter((i) => selected.includes(i.id));
    const header = ["start", "end", "title", "tutors", "status", "location"];
    const lines = chosen.map((i) =>
      [
        i.start,
        i.end,
        i.title,
        i.tutors.map((p) => p.name).join("; "),
        i.status,
        i.online ? "online" : i.location,
      ]
        .map((v) => csvCell(String(v ?? "")))
        .join(","),
    );
    const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "lessons.csv";
    link.click();
    URL.revokeObjectURL(url);
  };
  if (!selected.length) return null;
  const failed = run.data ? Object.keys(run.data.failed).length : 0;
  return (
    <div
      role="region"
      aria-label={t("g3.calendar.bulkTitle")}
      className="mb-3 flex flex-wrap items-end gap-2 rounded-md border border-border p-3"
    >
      <p className="mr-2 text-sm font-medium" aria-live="polite">
        {t("g3.calendar.selected", { count: selected.length })}
      </p>
      {canEdit ? (
        <>
          <SelectField
            label={t("g3.calendar.action")}
            value={action}
            onChange={(e) => setAction(e.target.value as BulkAction)}
            options={(
              ["complete", "cancel", "reassign_tutor", "change_location", "delete"] as const
            ).map((a) => ({ value: a, label: t(`g3.calendar.actions.${a}`) }))}
          />
          {action === "reassign_tutor" ? (
            <SelectField
              label={t("calendar.tutor")}
              value={tutor}
              onChange={(e) => setTutor(e.target.value)}
              options={[
                { value: "", label: t("g3.calendar.chooseTutor") },
                ...tutors.map((p) => ({ value: p.id, label: p.name })),
              ]}
            />
          ) : null}
          {action === "change_location" ? (
            <SelectField
              label={t("g3.calendar.location")}
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              options={[
                { value: "", label: t("calendar.online") },
                ...(locations.data?.results ?? []).map((l) => ({ value: l.id, label: l.name })),
              ]}
            />
          ) : null}
          <Button
            size="sm"
            onClick={() => run.mutate()}
            disabled={run.isPending || (action === "reassign_tutor" && !tutor)}
          >
            {t("g3.calendar.apply")}
          </Button>
        </>
      ) : null}
      <Button size="sm" variant="secondary" onClick={exportCsv}>
        {t("g3.calendar.export")}
      </Button>
      {run.isError ? <Alert tone="danger">{t("errors.generic")}</Alert> : null}
      {run.data && failed ? (
        <Alert tone="warning">{t("g3.calendar.someFailed", { count: failed })}</Alert>
      ) : null}
    </div>
  );
}
