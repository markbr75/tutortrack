import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, ErrorFallback, SelectField, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, usePermission } from "../api";
import { colourFor, rangeFor, sameDay, shift, STATUS_COLOURS, type View } from "./dates";
import { NewLesson } from "./NewLesson";
import { AgendaView, MonthView } from "./OtherViews";
import { ErrorList } from "./ErrorList";
import { QuickView } from "./QuickView";
import { TimeGrid, type GridColumn } from "./TimeGrid";
import type { CalendarItem } from "./types";

const VIEWS: View[] = ["day", "week", "month", "agenda", "tutors"];
type ColourBy = "service" | "tutor" | "status" | "location";

/** The calendar (FR-08-7): day, week, month, agenda and a tutors resource view, with
 * filters, colour modes, drag-to-reschedule and click-to-create. */
export function CalendarPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canCreate = usePermission("scheduling.lesson.create");
  const canEdit = usePermission("scheduling.lesson.edit");
  const [view, setView] = useState<View>("week");
  const [anchor, setAnchor] = useState(() => new Date());
  const [colourBy, setColourBy] = useState<ColourBy>("service");
  const [tutorFilter, setTutorFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState<CalendarItem | null>(null);
  const [creating, setCreating] = useState<{ start: Date; tutor?: string } | null>(null);
  const range = rangeFor(view, anchor);

  const query = {
    start: range.start.toISOString(),
    end: range.end.toISOString(),
    ...(tutorFilter ? { tutor: [tutorFilter] } : {}),
    ...(statusFilter ? { status: [statusFilter] } : {}),
  };
  const calendar = useQuery({
    queryKey: ["calendar", query],
    queryFn: async () => unwrap(await api.GET("/api/v1/calendar", { params: { query } })),
  });
  const tutors = useQuery({
    queryKey: ["tutors", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active"], page_size: 200 } },
        }),
      ),
  });

  const move = useMutation({
    mutationFn: async ({ item, start }: { item: CalendarItem; start: Date }) => {
      const duration = new Date(item.end).getTime() - new Date(item.start).getTime();
      return unwrap(
        await api.POST("/api/v1/lessons/{id}/reschedule", {
          params: { path: { id: item.id } },
          body: {
            start: start.toISOString(),
            end: new Date(start.getTime() + duration).toISOString(),
            reason: "",
            notify: true,
            override_conflicts: false,
          },
        }),
      );
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["calendar"] }),
  });

  const colour = useMemo(
    () =>
      (item: CalendarItem): string => {
        if (item.kind === "event") return item.colour;
        if (colourBy === "status") return STATUS_COLOURS[item.status] ?? "#2563eb";
        if (colourBy === "tutor") return colourFor(item.tutors[0]?.id ?? "none");
        if (colourBy === "location")
          return colourFor(item.online ? "online" : item.location || "none");
        return item.colour || "#2563eb";
      },
    [colourBy],
  );

  const items = calendar.data ?? [];
  const title =
    view === "month"
      ? anchor.toLocaleDateString(i18n.language, { month: "long", year: "numeric" })
      : view === "day" || view === "tutors"
        ? anchor.toLocaleDateString(i18n.language, {
            weekday: "long",
            day: "numeric",
            month: "long",
          })
        : `${range.days[0]?.toLocaleDateString(i18n.language, { day: "numeric", month: "short" })} – ${range.days[6]?.toLocaleDateString(i18n.language, { day: "numeric", month: "short", year: "numeric" })}`;

  let columns: GridColumn[] = [];
  if (view === "day" || view === "week") {
    columns = range.days.map((day) => ({
      key: day.toISOString(),
      day,
      label: day.toLocaleDateString(i18n.language, { weekday: "short", day: "numeric" }),
      items: items.filter((i) => sameDay(new Date(i.start), day)),
    }));
  } else if (view === "tutors") {
    const day = range.days[0] ?? anchor;
    const dayItems = items.filter((i) => sameDay(new Date(i.start), day));
    const people = (tutors.data?.results ?? []).filter((p) => !tutorFilter || p.id === tutorFilter);
    columns = [
      ...people.map((p) => ({
        key: p.id,
        day,
        label: p.full_name,
        items: dayItems.filter(
          (i) => i.tutors.some((x) => x.id === p.id) || (i.kind === "event" && i.org_wide),
        ),
      })),
      {
        key: "unassigned",
        day,
        label: t("calendar.unassigned"),
        items: dayItems.filter((i) => i.kind === "lesson" && i.tutors.length === 0),
      },
    ];
  }

  return (
    <section>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t("calendar.title")}</h1>
        {canCreate ? (
          <Button onClick={() => setCreating({ start: nextHalfHour() })}>
            {t("calendar.new.title")}
          </Button>
        ) : null}
      </div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div role="group" aria-label={t("calendar.navigate")} className="flex gap-1">
          <Button
            size="sm"
            variant="secondary"
            aria-label={t("calendar.previous")}
            onClick={() => setAnchor(shift(view, anchor, -1))}
          >
            ‹
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setAnchor(new Date())}>
            {t("calendar.today")}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            aria-label={t("calendar.next")}
            onClick={() => setAnchor(shift(view, anchor, 1))}
          >
            ›
          </Button>
        </div>
        <h2 className="min-w-48 font-medium" aria-live="polite">
          {title}
        </h2>
        <div role="group" aria-label={t("calendar.view")} className="flex flex-wrap gap-1">
          {VIEWS.map((v) => (
            <Button
              key={v}
              size="sm"
              variant={view === v ? "primary" : "secondary"}
              aria-pressed={view === v}
              onClick={() => setView(v)}
            >
              {t(`calendar.views.${v}`)}
            </Button>
          ))}
        </div>
        <SelectField
          label={t("calendar.tutor")}
          value={tutorFilter}
          onChange={(e) => setTutorFilter(e.target.value)}
          options={[
            { value: "", label: t("calendar.allTutors") },
            ...(tutors.data?.results ?? []).map((p) => ({ value: p.id, label: p.full_name })),
          ]}
        />
        <SelectField
          label={t("calendar.statusLabel")}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          options={[
            { value: "", label: t("people.anyStatus") },
            ...["planned", "completed", "cancelled", "missed"].map((s) => ({
              value: s,
              label: t(`calendar.status.${s}`),
            })),
          ]}
        />
        <SelectField
          label={t("calendar.colourBy")}
          value={colourBy}
          onChange={(e) => setColourBy(e.target.value as ColourBy)}
          options={(["service", "tutor", "status", "location"] as const).map((c) => ({
            value: c,
            label: t(`calendar.colour.${c}`),
          }))}
        />
      </div>
      {move.isError ? (
        <div className="mb-3">
          <ErrorList error={move.error} />
        </div>
      ) : null}
      {move.isSuccess && move.data.warnings.length ? (
        <Alert tone="warning" className="mb-3">
          {move.data.warnings.map((w) => w.message).join(" ")}
        </Alert>
      ) : null}
      {calendar.isError ? (
        <ErrorFallback
          title={t("errors.generic")}
          retryLabel={t("errors.retry")}
          onRetry={() => void calendar.refetch()}
        />
      ) : calendar.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : view === "month" ? (
        <MonthView
          days={range.days}
          month={anchor.getMonth()}
          items={items}
          colour={colour}
          onSelect={setSelected}
          onDay={(day) => {
            setAnchor(day);
            setView("day");
          }}
        />
      ) : view === "agenda" ? (
        <AgendaView days={range.days} items={items} colour={colour} onSelect={setSelected} />
      ) : (
        <TimeGrid
          columns={columns}
          colour={colour}
          onSelect={setSelected}
          onMove={
            canEdit && view !== "tutors" ? (item, start) => move.mutate({ item, start }) : undefined
          }
          onCreate={
            canCreate
              ? (start, key) =>
                  setCreating({
                    start,
                    tutor: view === "tutors" && key !== "unassigned" ? key : undefined,
                  })
              : undefined
          }
        />
      )}
      <QuickView item={selected} onClose={() => setSelected(null)} />
      <NewLesson
        start={creating?.start ?? null}
        tutorId={creating?.tutor}
        onClose={() => setCreating(null)}
      />
    </section>
  );
}

function nextHalfHour(): Date {
  const d = new Date();
  d.setMinutes(d.getMinutes() < 30 ? 30 : 60, 0, 0);
  return d;
}
