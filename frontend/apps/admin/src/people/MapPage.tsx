import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PageHeader,
  Panel,
  Segmented,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePermission } from "../api";

type Point = components["schemas"]["MapPoint"];
type Kind = "all" | "student" | "tutor";

const WIDTH = 640;
const HEIGHT = 420;
const PAD = 24;

/** Places points on a flat (equirectangular) projection scaled to the points shown. It is a
 * schematic plot, not a street map: no tiles, no addresses, coordinates rounded by the API. */
function project(points: Point[]) {
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  const pad = 0.005;
  const minLat = Math.min(...lats) - pad;
  const maxLat = Math.max(...lats) + pad;
  const minLng = Math.min(...lngs) - pad;
  const maxLng = Math.max(...lngs) + pad;
  // Keep the aspect ratio honest: a degree of longitude is shorter away from the equator.
  const midLat = ((minLat + maxLat) / 2) * (Math.PI / 180);
  const spanX = (maxLng - minLng) * Math.cos(midLat);
  const spanY = maxLat - minLat;
  const scale = Math.min((WIDTH - 2 * PAD) / spanX, (HEIGHT - 2 * PAD) / spanY);
  const kmPerDegree = 111.32;
  return {
    x: (lng: number) => PAD + (lng - minLng) * Math.cos(midLat) * scale,
    y: (lat: number) => HEIGHT - PAD - (lat - minLat) * scale,
    km: (km: number) => (km / kmPerDegree) * scale,
  };
}

function Marker({
  point,
  selected,
  x,
  y,
  radius,
  onSelect,
}: {
  point: Point;
  selected: boolean;
  x: number;
  y: number;
  radius: number | null;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const label = t("peopleMap.markerLabel", {
    kind: t(`peopleMap.kinds.${point.kind}`),
    name: point.name,
    area: point.area || t("peopleMap.noArea"),
  });
  const size = selected ? 9 : 6;
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-pressed={selected}
      onClick={() => onSelect(point.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(point.id);
        }
      }}
      className="cursor-pointer focus:outline-none [&:focus>.ring]:opacity-100"
    >
      <title>{label}</title>
      {radius ? (
        <circle
          cx={x}
          cy={y}
          r={radius}
          className="fill-link/10 stroke-link/40"
          strokeDasharray="4 3"
        />
      ) : null}
      <circle cx={x} cy={y} r={size + 5} className="ring fill-none stroke-foreground opacity-0" />
      {point.kind === "tutor" ? (
        <rect
          x={x - size}
          y={y - size}
          width={size * 2}
          height={size * 2}
          className="fill-link stroke-surface"
          strokeWidth={1.5}
        />
      ) : (
        <circle cx={x} cy={y} r={size} className="fill-warning stroke-surface" strokeWidth={1.5} />
      )}
    </g>
  );
}

/** E05-T12: students and tutors on a map for in-person matching, with a list that carries
 * the same information (the accessible alternative, WCAG 1.1.1 / 1.3.1). */
export function PeopleMapPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEditStudents = usePermission("people.student.edit");
  const canEditTutors = usePermission("people.tutor.edit");
  const canGeocode = canEditStudents || canEditTutors;
  const [kind, setKind] = useState<Kind>("all");
  const [status, setStatus] = useState("");
  const [subject, setSubject] = useState("");
  const [radius, setRadius] = useState(true);
  const [view, setView] = useState<"map" | "list">("map");
  const [selected, setSelected] = useState<string | null>(null);
  const map = useQuery({
    queryKey: ["people-map", kind, status, subject],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/people/map", {
          params: {
            query: {
              kind,
              ...(status ? { status } : {}),
              ...(subject ? { subject } : {}),
            },
          },
        }),
      ),
  });
  const geocode = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/people/map/geocode", { body: { kinds: ["student", "tutor"] } }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["people-map"] }),
  });
  const points = map.data?.points ?? [];
  const missing = (map.data?.missing.student ?? 0) + (map.data?.missing.tutor ?? 0);
  const chosen = points.find((p) => p.id === selected) ?? null;
  const proj = points.length ? project(points) : null;
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("peopleMap.title")}
        description={<span className="block max-w-prose">{t("peopleMap.intro")}</span>}
        actions={
          <Segmented
            label={t("peopleMap.viewAs")}
            value={view}
            onChange={setView}
            options={[
              { key: "map", label: t("peopleMap.mapView") },
              { key: "list", label: t("peopleMap.listView") },
            ]}
          />
        }
        className="mb-2"
      />
      <form
        role="search"
        className="flex flex-wrap items-center gap-2"
        aria-label={t("peopleMap.filters")}
        onSubmit={(e) => e.preventDefault()}
      >
        <SelectField
          label={t("peopleMap.show")}
          hideLabel
          size="sm"
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
          options={[
            { value: "all", label: t("peopleMap.kinds.all") },
            { value: "student", label: t("peopleMap.kinds.studentPlural") },
            { value: "tutor", label: t("peopleMap.kinds.tutorPlural") },
          ]}
        />
        <div className="min-w-40 flex-1 sm:max-w-56">
          <TextField
            label={t("peopleMap.status")}
            hideLabel
            size="sm"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            placeholder={t("peopleMap.status")}
          />
        </div>
        <div className="min-w-40 flex-1 sm:max-w-56">
          <TextField
            label={t("peopleMap.subject")}
            hideLabel
            size="sm"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder={t("peopleMap.subject")}
          />
        </div>
        <label className="flex h-9 items-center gap-2 px-1 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={radius}
            onChange={(e) => setRadius(e.target.checked)}
          />
          {t("peopleMap.showRadius")}
        </label>
      </form>
      {map.isLoading ? <Spinner label={t("grid.loading")} /> : null}
      {map.error ? <Alert tone="danger">{map.error.message}</Alert> : null}
      {missing > 0 ? (
        <Alert tone="info">
          <p>{t("peopleMap.missing", { count: missing })}</p>
          {canGeocode ? (
            <Button
              size="sm"
              variant="secondary"
              className="mt-2"
              disabled={geocode.isPending}
              onClick={() => geocode.mutate()}
            >
              {t("peopleMap.geocode")}
            </Button>
          ) : null}
          {geocode.data ? (
            <p role="status" className="mt-1">
              {t("peopleMap.queued", { count: geocode.data.queued })}
            </p>
          ) : null}
        </Alert>
      ) : null}
      {map.data && points.length === 0 ? (
        <p className="rounded-xl border border-border bg-surface px-4 py-10 text-center text-sm text-muted-foreground">
          {t("peopleMap.empty")}
        </p>
      ) : null}
      {view === "map" && proj ? (
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <figure className="min-w-0 rounded-xl border border-border bg-surface">
            <svg
              role="group"
              aria-label={t("peopleMap.mapLabel", { count: points.length })}
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="block w-full rounded-t-xl"
            >
              {points.map((p) => (
                <Marker
                  key={`${p.kind}-${p.id}`}
                  point={p}
                  selected={p.id === selected}
                  x={proj.x(p.lng)}
                  y={proj.y(p.lat)}
                  radius={radius && p.travel_radius_km ? proj.km(p.travel_radius_km) : null}
                  onSelect={setSelected}
                />
              ))}
            </svg>
            <figcaption className="flex flex-wrap gap-x-4 gap-y-1 border-t border-rule px-5 py-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5 text-foreground">
                <svg width="14" height="14" aria-hidden="true">
                  <circle cx="7" cy="7" r="5" className="fill-warning" />
                </svg>
                {t("peopleMap.kinds.studentPlural")}
              </span>
              <span className="flex items-center gap-1.5 text-foreground">
                <svg width="14" height="14" aria-hidden="true">
                  <rect x="2" y="2" width="10" height="10" className="fill-link" />
                </svg>
                {t("peopleMap.kinds.tutorPlural")}
              </span>
              <span>{t("peopleMap.schematic")}</span>
            </figcaption>
          </figure>
          <div aria-live="polite">
            {chosen ? (
              <Panel title={chosen.name}>
                <p className="text-sm text-muted-foreground">
                  {t(`peopleMap.kinds.${chosen.kind}`)} · {chosen.area || t("peopleMap.noArea")}
                  {chosen.subjects.length ? ` · ${chosen.subjects.join(", ")}` : ""}
                </p>
                <Link
                  to={chosen.kind === "tutor" ? "/tutors/$tutorId" : "/students/$studentId"}
                  params={
                    chosen.kind === "tutor" ? { tutorId: chosen.id } : { studentId: chosen.id }
                  }
                  className="mt-2 inline-block text-sm font-medium text-link underline-offset-2 hover:underline"
                >
                  {t("peopleMap.open")}
                </Link>
              </Panel>
            ) : (
              <p className="rounded-xl border border-border bg-surface px-5 py-4 text-sm text-muted-foreground">
                {t("designS5.map.choose")}
              </p>
            )}
          </div>
        </div>
      ) : null}
      {view === "list" || !proj ? <PointList points={points} /> : null}
    </div>
  );
}

function PointList({ points }: { points: Point[] }) {
  const { t } = useTranslation();
  if (points.length === 0) return null;
  return (
    <div
      role="region"
      aria-label={t("peopleMap.listCaption")}
      tabIndex={0}
      className="overflow-x-auto rounded-xl border border-border bg-surface"
    >
      <table className="w-full text-sm [&_td]:px-4 [&_td]:py-2.5 [&_th]:px-4 [&_th]:py-2.5">
        <caption className="sr-only">{t("peopleMap.listCaption")}</caption>
        <thead className="border-b border-border">
          <tr className="text-left whitespace-nowrap">
            <th scope="col">{t("peopleMap.name")}</th>
            <th scope="col">{t("peopleMap.kind")}</th>
            <th scope="col">{t("peopleMap.area")}</th>
            <th scope="col">{t("peopleMap.subjects")}</th>
            <th scope="col">{t("peopleMap.radius")}</th>
          </tr>
        </thead>
        <tbody>
          {[...points]
            .sort((a, b) => a.area.localeCompare(b.area) || a.name.localeCompare(b.name))
            .map((p) => (
              <tr key={`${p.kind}-${p.id}`}>
                <td>
                  {p.kind === "tutor" ? (
                    <Link
                      to="/tutors/$tutorId"
                      params={{ tutorId: p.id }}
                      className="font-medium underline-offset-2 hover:underline"
                    >
                      {p.name}
                    </Link>
                  ) : (
                    <Link
                      to="/students/$studentId"
                      params={{ studentId: p.id }}
                      className="font-medium underline-offset-2 hover:underline"
                    >
                      {p.name}
                    </Link>
                  )}
                </td>
                <td>{t(`peopleMap.kinds.${p.kind}`)}</td>
                <td>{p.area || t("peopleMap.noArea")}</td>
                <td>{p.subjects.join(", ")}</td>
                <td className="tabular-nums">
                  {p.travel_radius_km ? t("peopleMap.km", { count: p.travel_radius_km }) : ""}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
