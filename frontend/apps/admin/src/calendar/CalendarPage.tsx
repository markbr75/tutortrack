import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, ErrorFallback, PageHeader, SelectField, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import { api, usePermission } from "../api";
import {
  BulkLessonBar,
  PrintTimetable,
  SavedFilterSets,
  SecondaryZoneSelect,
  type CalendarFilters,
} from "../g3/CalendarTools";
import { colourFor, rangeFor, sameDay, shift, STATUS_COLOURS, type View } from "./dates";
import { NewLesson } from "./NewLesson";
import { AgendaView, MonthView } from "./OtherViews";
import { ErrorList } from "./ErrorList";
import { QuickView } from "./QuickView";
import { TimeGrid, type GridColumn } from "./TimeGrid";
import type { CalendarItem } from "./types";

const VIEWS: View[] = ["day", "week", "month", "agenda", "tutors", "rooms"];
type ColourBy = "service" | "tutor" | "status" | "location";

/** The calendar (FR-08-7): day, week, month, agenda and tutors/rooms resource views, with
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
  const [selectedItem, setSelectedItem] = useState<CalendarItem | null>(null);
  const [creating, setCreating] = useState<{ start: Date; tutor?: string } | null>(null);
  const [secondaryZone, setSecondaryZone] = useState(() => readZone());
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const range = rangeFor(view, anchor);
  const applyFilters = (f: CalendarFilters) => {
    if (VIEWS.includes(f.view as View)) setView(f.view as View);
    setTutorFilter(f.tutor ?? "");
    setStatusFilter(f.status ?? "");
    if (["service", "tutor", "status", "location"].includes(f.colourBy))
      setColourBy(f.colourBy as ColourBy);
  };
  const chooseZone = (zone: string) => {
    setSecondaryZone(zone);
    try {
      localStorage.setItem(ZONE_KEY, zone);
    } catch {
      // storage can be unavailable (private mode): the choice lasts for this visit
    }
  };

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
  const rooms = useQuery({
    queryKey: ["calendar", "rooms", range.start.toISOString()],
    enabled: view === "rooms",
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/calendar/rooms", {
          params: { query: { start: range.start.toISOString(), end: range.end.toISOString() } },
        }),
      ),
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
        if (colourBy === "status") return STATUS_COLOURS[item.status] ?? "hsl(var(--tt-link))";
        if (colourBy === "tutor") return colourFor(item.tutors[0]?.id ?? "none");
        if (colourBy === "location")
          return colourFor(item.online ? "online" : item.location || "none");
        return item.colour || "hsl(var(--tt-link))";
      },
    [colourBy],
  );

  const items = calendar.data ?? [];
  const title =
    view === "month"
      ? anchor.toLocaleDateString(i18n.language, { month: "long", year: "numeric" })
      : view === "day" || view === "tutors" || view === "rooms"
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
  } else if (view === "rooms") {
    // E08-T12: rooms as columns (each lesson booked in it).
    const day = range.days[0] ?? anchor;
    columns = (rooms.data ?? []).map((room) => ({
      key: room.id,
      day,
      label: `${room.name} · ${room.location_name}`,
      items: room.lessons as CalendarItem[],
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
      <PageHeader
        title={t("calendar.title")}
        actions={
          canCreate ? (
            <Button onClick={() => setCreating({ start: nextHalfHour() })}>
              {t("calendar.new.title")}
            </Button>
          ) : null
        }
      />
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border pb-3">
        <div role="group" aria-label={t("calendar.navigate")} className="flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            className="w-8 px-0"
            aria-label={t("calendar.previous")}
            onClick={() => setAnchor(shift(view, anchor, -1))}
          >
            <ChevronLeft aria-hidden="true" className="size-4" />
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setAnchor(new Date())}>
            {t("calendar.today")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="w-8 px-0"
            aria-label={t("calendar.next")}
            onClick={() => setAnchor(shift(view, anchor, 1))}
          >
            <ChevronRight aria-hidden="true" className="size-4" />
          </Button>
        </div>
        <h2 className="min-w-48 text-base font-semibold" aria-live="polite">
          {title}
        </h2>
        <div
          role="group"
          aria-label={t("calendar.view")}
          className="flex w-full rounded-md border border-border bg-surface p-0.5 sm:ml-auto sm:w-auto"
        >
          {VIEWS.map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => setView(v)}
              className="h-7 flex-1 rounded px-2 text-sm text-muted-foreground sm:flex-none sm:px-3 hover:text-foreground aria-pressed:bg-foreground aria-pressed:font-medium aria-pressed:text-background"
            >
              {t(`calendar.views.${v}`)}
            </button>
          ))}
        </div>
      </div>
      <div className="mb-4 flex flex-wrap items-start gap-2">
        <SelectField
          label={t("calendar.tutor")}
          hideLabel
          size="sm"
          value={tutorFilter}
          onChange={(e) => setTutorFilter(e.target.value)}
          options={[
            { value: "", label: t("calendar.allTutors") },
            ...(tutors.data?.results ?? []).map((p) => ({ value: p.id, label: p.full_name })),
          ]}
        />
        <SelectField
          label={t("calendar.statusLabel")}
          hideLabel
          size="sm"
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
          hideLabel
          size="sm"
          value={colourBy}
          onChange={(e) => setColourBy(e.target.value as ColourBy)}
          options={(["service", "tutor", "status", "location"] as const).map((c) => ({
            value: c,
            label: t(`calendar.colourByOption.${c}`),
          }))}
        />
        {view === "agenda" ? (
          <Button
            size="sm"
            className="h-9"
            variant={selecting ? "primary" : "secondary"}
            aria-pressed={selecting}
            onClick={() => {
              setSelecting(!selecting);
              setSelected([]);
            }}
          >
            {t("g3.calendar.selectMode")}
          </Button>
        ) : null}
        {/* Less-used tools stay one click away instead of filling the first viewport. */}
        <details className="group">
          <summary className="flex h-9 cursor-pointer list-none items-center gap-1.5 rounded-md px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground">
            <SlidersHorizontal aria-hidden="true" className="size-4" />
            {t("calendar.moreOptions")}
          </summary>
          <div className="mt-2 flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-3">
            <SecondaryZoneSelect value={secondaryZone} onChange={chooseZone} />
            <PrintTimetable start={range.start} end={range.end} tutor={tutorFilter} />
            <SavedFilterSets
              current={{ view, tutor: tutorFilter, status: statusFilter, colourBy }}
              onApply={applyFilters}
            />
          </div>
        </details>
      </div>
      {selecting && view === "agenda" ? (
        <BulkLessonBar
          selected={selected}
          items={calendar.data ?? []}
          tutors={(tutors.data?.results ?? []).map((p) => ({ id: p.id, name: p.full_name }))}
          onDone={setSelected}
        />
      ) : null}
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
          onSelect={setSelectedItem}
          onDay={(day) => {
            setAnchor(day);
            setView("day");
          }}
        />
      ) : view === "agenda" ? (
        <AgendaView
          days={range.days}
          items={items}
          colour={colour}
          onSelect={setSelectedItem}
          secondaryZone={secondaryZone || undefined}
          selected={selecting ? selected : undefined}
          onToggle={
            selecting
              ? (id) =>
                  setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
              : undefined
          }
        />
      ) : (
        <TimeGrid
          columns={columns}
          byDay={view === "day" || view === "week"}
          colour={colour}
          secondaryZone={secondaryZone || undefined}
          onSelect={setSelectedItem}
          onMove={
            canEdit && view !== "tutors" && view !== "rooms"
              ? (item, start) => move.mutate({ item, start })
              : undefined
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
      <QuickView item={selectedItem} onClose={() => setSelectedItem(null)} />
      <NewLesson
        start={creating?.start ?? null}
        tutorId={creating?.tutor}
        onClose={() => setCreating(null)}
      />
    </section>
  );
}

const ZONE_KEY = "tt.calendar.secondaryZone";

function readZone(): string {
  try {
    return localStorage.getItem(ZONE_KEY) ?? "";
  } catch {
    return "";
  }
}

function nextHalfHour(): Date {
  const d = new Date();
  d.setMinutes(d.getMinutes() < 30 ? 30 : 60, 0, 0);
  return d;
}
