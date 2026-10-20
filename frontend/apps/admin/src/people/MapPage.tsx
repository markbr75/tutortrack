import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
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
          className="fill-sky-600/10 stroke-sky-700/40"
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
          className="fill-sky-700 stroke-white"
          strokeWidth={1.5}
        />
      ) : (
        <circle cx={x} cy={y} r={size} className="fill-warning stroke-black" strokeWidth={1} />
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
    <div className="space-y-4 p-6">
      <h1 className="text-2xl font-semibold">{t("peopleMap.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("peopleMap.intro")}</p>
      <form
        className="flex flex-wrap items-end gap-3"
        aria-label={t("peopleMap.filters")}
        onSubmit={(e) => e.preventDefault()}
      >
        <SelectField
          label={t("peopleMap.show")}
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
          options={[
            { value: "all", label: t("peopleMap.kinds.all") },
            { value: "student", label: t("peopleMap.kinds.studentPlural") },
            { value: "tutor", label: t("peopleMap.kinds.tutorPlural") },
          ]}
        />
        <TextField
          label={t("peopleMap.status")}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          placeholder="active"
        />
        <TextField
          label={t("peopleMap.subject")}
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={radius} onChange={(e) => setRadius(e.target.checked)} />
          {t("peopleMap.showRadius")}
        </label>
      </form>
      <div role="group" aria-label={t("peopleMap.viewAs")} className="flex gap-2">
        <Button
          variant={view === "map" ? "primary" : "secondary"}
          aria-pressed={view === "map"}
          onClick={() => setView("map")}
        >
          {t("peopleMap.mapView")}
        </Button>
        <Button
          variant={view === "list" ? "primary" : "secondary"}
          aria-pressed={view === "list"}
          onClick={() => setView("list")}
        >
          {t("peopleMap.listView")}
        </Button>
      </div>
      {map.isLoading ? <Spinner label={t("grid.loading")} /> : null}
      {map.error ? <Alert tone="danger">{map.error.message}</Alert> : null}
      {missing > 0 ? (
        <Alert tone="info">
          <p>{t("peopleMap.missing", { count: missing })}</p>
          {canGeocode ? (
            <Button
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
      {map.data && points.length === 0 ? <p>{t("peopleMap.empty")}</p> : null}
      {view === "map" && proj ? (
        <figure className="space-y-2">
          <svg
            role="group"
            aria-label={t("peopleMap.mapLabel", { count: points.length })}
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="w-full max-w-3xl rounded-md border border-border bg-muted/30"
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
          <figcaption className="flex flex-wrap gap-4 text-sm">
            <span className="flex items-center gap-1">
              <svg width="14" height="14" aria-hidden="true">
                <circle cx="7" cy="7" r="5" className="fill-warning stroke-black" />
              </svg>
              {t("peopleMap.kinds.studentPlural")}
            </span>
            <span className="flex items-center gap-1">
              <svg width="14" height="14" aria-hidden="true">
                <rect x="2" y="2" width="10" height="10" className="fill-sky-700" />
              </svg>
              {t("peopleMap.kinds.tutorPlural")}
            </span>
            <span>{t("peopleMap.schematic")}</span>
          </figcaption>
          {chosen ? (
            <section aria-live="polite" className="rounded-md border border-border p-3 text-sm">
              <h2 className="font-semibold">{chosen.name}</h2>
              <p>
                {t(`peopleMap.kinds.${chosen.kind}`)} · {chosen.area || t("peopleMap.noArea")}
                {chosen.subjects.length ? ` · ${chosen.subjects.join(", ")}` : ""}
              </p>
              <Link
                to={chosen.kind === "tutor" ? "/tutors/$tutorId" : "/students/$studentId"}
                params={chosen.kind === "tutor" ? { tutorId: chosen.id } : { studentId: chosen.id }}
                className="underline underline-offset-2"
              >
                {t("peopleMap.open")}
              </Link>
            </section>
          ) : null}
        </figure>
      ) : null}
      {view === "list" || !proj ? <PointList points={points} /> : null}
    </div>
  );
}

function PointList({ points }: { points: Point[] }) {
  const { t } = useTranslation();
  if (points.length === 0) return null;
  return (
    <table className="w-full max-w-3xl text-sm">
      <caption className="sr-only">{t("peopleMap.listCaption")}</caption>
      <thead>
        <tr className="text-left">
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
            <tr key={`${p.kind}-${p.id}`} className="border-t border-border">
              <td>
                {p.kind === "tutor" ? (
                  <Link to="/tutors/$tutorId" params={{ tutorId: p.id }} className="underline">
                    {p.name}
                  </Link>
                ) : (
                  <Link
                    to="/students/$studentId"
                    params={{ studentId: p.id }}
                    className="underline"
                  >
                    {p.name}
                  </Link>
                )}
              </td>
              <td>{t(`peopleMap.kinds.${p.kind}`)}</td>
              <td>{p.area || t("peopleMap.noArea")}</td>
              <td>{p.subjects.join(", ")}</td>
              <td>{p.travel_radius_km ? t("peopleMap.km", { count: p.travel_radius_km }) : ""}</td>
            </tr>
          ))}
      </tbody>
    </table>
  );
}
