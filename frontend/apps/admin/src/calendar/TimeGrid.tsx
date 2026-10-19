import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { RegisterMark, registerMarkFor } from "@tutortrack/ui";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { timeIn } from "../g3/zones";
import { minutesOfDay, sameDay } from "./dates";
import type { CalendarItem } from "./types";

const FIRST_HOUR = 7;
const LAST_HOUR = 22;
const PX_PER_MIN = 1;
const SNAP = 15;

export interface GridColumn {
  key: string;
  label: string;
  day: Date;
  items: CalendarItem[];
}

interface Props {
  columns: GridColumn[];
  colour: (item: CalendarItem) => string;
  onSelect: (item: CalendarItem) => void;
  onMove?: (item: CalendarItem, start: Date, columnKey: string) => void;
  onCreate?: (start: Date, columnKey: string) => void;
  /** Gap G3: a second hour column in this timezone (FR-08-7). */
  secondaryZone?: string;
  /** Columns are days (day/week), so today's header is marked; tutor and room columns are not. */
  byDay?: boolean;
}

/** Side-by-side lanes for overlapping items in one column. */
function lanes(items: CalendarItem[]): Map<string, { lane: number; of: number }> {
  const sorted = [...items].sort((a, b) => a.start.localeCompare(b.start));
  const out = new Map<string, { lane: number; of: number }>();
  let cluster: CalendarItem[] = [];
  let clusterEnd = "";
  const flush = () => {
    const laneEnds: string[] = [];
    const assigned: [string, number][] = [];
    for (const item of cluster) {
      let lane = laneEnds.findIndex((end) => end <= item.start);
      if (lane === -1) {
        lane = laneEnds.length;
        laneEnds.push(item.end);
      } else {
        laneEnds[lane] = item.end;
      }
      assigned.push([`${item.kind}-${item.id}`, lane]);
    }
    for (const [key, lane] of assigned) out.set(key, { lane, of: laneEnds.length });
    cluster = [];
  };
  for (const item of sorted) {
    if (cluster.length && item.start >= clusterEnd) flush();
    cluster.push(item);
    clusterEnd = clusterEnd > item.end && cluster.length > 1 ? clusterEnd : item.end;
  }
  if (cluster.length) flush();
  return out;
}

interface Drag {
  item: CalendarItem;
  x: number;
  y: number;
  dx: number;
  dy: number;
  moved: boolean;
}

/** Day/week/resource time grid with click-to-create and drag-to-reschedule. Every item is
 * a button, so keyboard users open the quick view and reschedule there (WCAG 2.5.7). */
export function TimeGrid({
  columns,
  colour,
  onSelect,
  onMove,
  onCreate,
  secondaryZone,
  byDay = false,
}: Props) {
  const { t, i18n } = useTranslation();
  const gridRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const height = (LAST_HOUR - FIRST_HOUR) * 60 * PX_PER_MIN;
  const hours = Array.from({ length: LAST_HOUR - FIRST_HOUR }, (_, i) => FIRST_HOUR + i);
  // The NOW rule moves with the clock.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const columnWidth = () => {
    const grid = gridRef.current;
    return grid ? grid.clientWidth / Math.max(columns.length, 1) : 1;
  };

  const draggable = (item: CalendarItem) =>
    Boolean(onMove) && item.kind === "lesson" && !item.locked && item.status === "planned";

  const startDrag = (e: ReactPointerEvent, item: CalendarItem) => {
    if (!draggable(item)) return;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    setDrag({ item, x: e.clientX, y: e.clientY, dx: 0, dy: 0, moved: false });
  };

  const moveDrag = (e: ReactPointerEvent) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    setDrag({ ...drag, dx, dy, moved: drag.moved || Math.abs(dx) > 4 || Math.abs(dy) > 4 });
  };

  const endDrag = (columnIndex: number) => {
    if (!drag) return;
    const { item, dx, dy, moved } = drag;
    setDrag(null);
    if (!moved) {
      onSelect(item);
      return;
    }
    const minutes = Math.round(dy / PX_PER_MIN / SNAP) * SNAP;
    const shiftCols = Math.round(dx / columnWidth());
    const target = columns[Math.min(Math.max(columnIndex + shiftCols, 0), columns.length - 1)];
    const source = columns[columnIndex];
    if (!target || !source || (minutes === 0 && target.key === source.key)) return;
    const start = new Date(item.start);
    const dayShift = Math.round((target.day.getTime() - source.day.getTime()) / 86_400_000);
    start.setDate(start.getDate() + dayShift);
    start.setMinutes(start.getMinutes() + minutes);
    onMove?.(item, start, target.key);
  };

  const create = (e: ReactPointerEvent<HTMLDivElement>, column: GridColumn) => {
    if (!onCreate || e.target !== e.currentTarget) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const minutes = Math.floor((e.clientY - rect.top) / PX_PER_MIN / 30) * 30 + FIRST_HOUR * 60;
    const start = new Date(column.day);
    start.setHours(0, minutes, 0, 0);
    onCreate(start, column.key);
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <div className="flex min-w-[40rem]">
        <div className="w-14 shrink-0" aria-hidden="true">
          <div className="h-10 border-b border-border" />
          <div className="relative" style={{ height }}>
            {hours.map((h) => (
              <div
                key={h}
                className="absolute right-1 -translate-y-2 text-xs text-muted-foreground"
                style={{ top: (h - FIRST_HOUR) * 60 * PX_PER_MIN }}
              >
                {String(h).padStart(2, "0")}:00
              </div>
            ))}
          </div>
        </div>
        {secondaryZone ? (
          <div className="w-16 shrink-0 border-l border-border" aria-hidden="true">
            <div className="flex h-10 items-center justify-center border-b border-border px-1 text-center text-xs leading-tight text-muted-foreground">
              {secondaryZone.split("/").pop()?.replace("_", " ")}
            </div>
            <div className="relative" style={{ height }}>
              {hours.map((h) => {
                const at = new Date(columns[0]?.day ?? now);
                at.setHours(h, 0, 0, 0);
                return (
                  <div
                    key={h}
                    className="absolute right-1 -translate-y-2 text-xs text-muted-foreground"
                    style={{ top: (h - FIRST_HOUR) * 60 * PX_PER_MIN }}
                  >
                    {timeIn(at, secondaryZone, i18n.language)}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
        <div className="flex flex-1" ref={gridRef}>
          {columns.map((column, columnIndex) => {
            const layout = lanes(column.items);
            const isToday = sameDay(column.day, now);
            return (
              <div key={column.key} className="min-w-0 flex-1 border-l border-border">
                <div
                  aria-current={byDay && isToday ? "date" : undefined}
                  className={`flex h-10 items-center justify-center border-b border-border text-sm ${byDay && isToday ? "font-semibold text-margin" : ""}`}
                >
                  {column.label}
                </div>
                <div
                  className="relative"
                  style={{
                    height,
                    backgroundImage:
                      "repeating-linear-gradient(to bottom, transparent 0, transparent 59px, var(--color-rule) 59px, var(--color-rule) 60px)",
                  }}
                  onPointerDown={(e) => create(e, column)}
                  data-testid={`column-${column.key}`}
                >
                  {isToday &&
                  minutesOfDay(now) >= FIRST_HOUR * 60 &&
                  minutesOfDay(now) < LAST_HOUR * 60 ? (
                    <div
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-x-0 z-20 border-t-2 border-margin"
                      style={{ top: (minutesOfDay(now) - FIRST_HOUR * 60) * PX_PER_MIN }}
                    >
                      <span className="absolute -top-[5px] -left-[5px] size-2 rounded-full bg-margin" />
                    </div>
                  ) : null}
                  {column.items.map((item) => {
                    const start = new Date(item.start);
                    const end = new Date(item.end);
                    const top = Math.max(minutesOfDay(start) - FIRST_HOUR * 60, 0) * PX_PER_MIN;
                    const bottom = Math.min(
                      sameDay(start, end) ? minutesOfDay(end) - FIRST_HOUR * 60 : height,
                      height,
                    );
                    const pos = layout.get(`${item.kind}-${item.id}`) ?? { lane: 0, of: 1 };
                    const dragging = drag?.item.id === item.id && drag.item.kind === item.kind;
                    const cancelled = item.status === "cancelled";
                    return (
                      <button
                        key={`${item.kind}-${item.id}`}
                        type="button"
                        className={`absolute overflow-hidden rounded-md border px-1.5 py-1 text-left text-xs text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 ${cancelled ? "line-through opacity-70" : ""}`}
                        style={{
                          top: top + (dragging ? drag.dy : 0),
                          height: Math.max(bottom - top, 18),
                          left: `calc(${(pos.lane / pos.of) * 100}% + ${dragging ? drag.dx : 0}px)`,
                          width: `calc(${100 / pos.of}% - 2px)`,
                          // A tint of the category colour with its edge: ink stays readable on any colour.
                          background: `color-mix(in srgb, ${colour(item)} 16%, hsl(var(--tt-surface)))`,
                          borderColor: colour(item),
                          touchAction: "none",
                          zIndex: dragging ? 10 : 1,
                        }}
                        aria-label={t("calendar.itemLabel", {
                          title: item.title,
                          when: formatDateTime(item.start, i18n.language),
                          status: t(`calendar.status.${item.status}`, {
                            defaultValue: item.status,
                          }),
                        })}
                        onPointerDown={(e) => {
                          e.stopPropagation();
                          startDrag(e, item);
                        }}
                        onPointerMove={moveDrag}
                        onPointerUp={() => endDrag(columnIndex)}
                        onClick={(e) => {
                          // Pointer users are handled on pointer up; keyboard "clicks" have no pointer.
                          if (e.detail === 0 || !draggable(item)) onSelect(item);
                        }}
                      >
                        <span className="flex items-start gap-1">
                          {item.kind === "lesson" ? (
                            <RegisterMark
                              kind={registerMarkFor(item.status, item.end, now)}
                              label={t(`calendar.status.${item.status}`, {
                                defaultValue: item.status,
                              })}
                              className="size-3.5 shrink-0"
                            />
                          ) : null}
                          <span className="font-medium">{item.title}</span>
                        </span>
                        {start.toLocaleTimeString(i18n.language, {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
