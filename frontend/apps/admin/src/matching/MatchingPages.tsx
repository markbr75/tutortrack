import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";

import { api, usePermission } from "../api";

type Row = components["schemas"]["MatchRow"];
type Point = components["schemas"]["Point"];
type Batch = components["schemas"]["OfferBatch"];
type Posting = components["schemas"]["JobPostingDetail"];
type Cover = components["schemas"]["CoverRequest"];

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const linkClass = "underline underline-offset-2";

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-3 rounded-lg border border-border p-4">
      <h2 className="font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** Where the candidates live, relative to the lessons (rounded points, no street map). */
export function MatchMap({ origin, rows }: { origin: Point | null; rows: Row[] }) {
  const { t } = useTranslation();
  const points = rows.filter((r) => r.point).map((r) => ({ row: r, p: r.point as Point }));
  if (!origin && points.length === 0) return null;
  const all = [...points.map((x) => x.p), ...(origin ? [origin] : [])];
  const lats = all.map((p) => p.lat);
  const lngs = all.map((p) => p.lng);
  const pad = 0.01;
  const [minLat, maxLat] = [Math.min(...lats) - pad, Math.max(...lats) + pad];
  const [minLng, maxLng] = [Math.min(...lngs) - pad, Math.max(...lngs) + pad];
  const x = (lng: number) => ((lng - minLng) / (maxLng - minLng)) * 280 + 10;
  const y = (lat: number) => (1 - (lat - minLat) / (maxLat - minLat)) * 180 + 10;
  return (
    <svg
      role="img"
      aria-label={t("matching.mapLabel", { count: points.length })}
      viewBox="0 0 300 200"
      className="h-48 w-full max-w-md rounded-md border border-border bg-muted/30"
    >
      {origin ? (
        <g>
          <title>{t("matching.lessons")}</title>
          <rect
            x={x(origin.lng) - 5}
            y={y(origin.lat) - 5}
            width={10}
            height={10}
            fill="currentColor"
          />
        </g>
      ) : null}
      {points.map(({ row, p }) => (
        <g key={row.tutor.id}>
          <title>{`${row.rank}. ${row.tutor.name} (${row.score})`}</title>
          <circle cx={x(p.lng)} cy={y(p.lat)} r={6} className="fill-primary/70" />
          <text x={x(p.lng)} y={y(p.lat) + 3} textAnchor="middle" className="fill-white text-[7px]">
            {row.rank}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** How much of each weekly slot the tutor is free for (the availability heatmap). */
function SlotFit({ fit, slots }: { fit: number[]; slots: { weekday: number; time: string }[] }) {
  const { t } = useTranslation();
  if (fit.length === 0)
    return <span className="text-muted-foreground">{t("matching.unknown")}</span>;
  return (
    <ul className="flex gap-1" aria-label={t("matching.availability")}>
      {fit.map((share, i) => {
        const slot = slots[i];
        const label = slot ? `${t(`matching.days.${WEEKDAYS[slot.weekday]}`)} ${slot.time}` : "";
        const pct = Math.round(share * 100);
        return (
          <li
            key={i}
            title={`${label}: ${pct}%`}
            className={
              "rounded px-1 text-xs " +
              (pct >= 100
                ? "bg-green-700 text-white"
                : pct >= 50
                  ? "bg-amber-300 text-black"
                  : "bg-muted text-foreground")
            }
          >
            {label ? `${label} ` : ""}
            {pct}%
          </li>
        );
      })}
    </ul>
  );
}

function Breakdown({ row }: { row: Row }) {
  const { t } = useTranslation();
  return (
    <details className="text-xs">
      <summary className="cursor-pointer">{t("matching.why")}</summary>
      <table className="mt-1">
        <tbody>
          {Object.entries(row.breakdown).map(([key, f]) => (
            <tr key={key}>
              <th scope="row" className="pr-2 text-left font-normal">
                {t(`matching.factors.${key}`)}
              </th>
              <td className="pr-2">
                {f.known ? `${Math.round(f.score * 100)}%` : t("matching.unknown")}
              </td>
              <td className="pr-2 text-muted-foreground">
                {f.value === null || f.value === undefined ? "" : String(f.value)}
              </td>
              <td className="text-muted-foreground">×{f.weight}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {row.reasons.length ? <p className="mt-1 text-red-700">{row.reasons.join(" · ")}</p> : null}
    </details>
  );
}

/** Find a tutor for a job: ranked matches, shortlist, offers and the job board (FR-19-1..3). */
export function JobMatchPage({ jobId }: { jobId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canRestricted = usePermission("matching.include_restricted");
  const canOffer = usePermission("matching.offer.manage");
  const canPost = usePermission("matching.posting.manage");
  const [includeRestricted, setIncludeRestricted] = useState(false);
  const [chosen, setChosen] = useState<string[]>([]);
  const [mode, setMode] = useState<"sequential" | "simultaneous">("sequential");
  const [expiry, setExpiry] = useState("24");
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/jobs/{id}", { params: { path: { id: jobId } } })),
  });
  const results = useQuery({
    queryKey: ["matching", jobId, includeRestricted],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/matching/search", {
          body: { job: jobId, include_restricted: includeRestricted, limit: 50 },
        }),
      ),
  });
  const batches = useQuery({
    queryKey: ["offer-batches", jobId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/job-offer-batches", { params: { query: { job: jobId } } })),
    enabled: canOffer,
  });
  const postings = useQuery({
    queryKey: ["postings", jobId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/job-postings", { params: { query: { job: jobId } } })),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["matching", jobId] });
    void queryClient.invalidateQueries({ queryKey: ["offer-batches", jobId] });
    void queryClient.invalidateQueries({ queryKey: ["postings", jobId] });
  };
  const shortlist = useMutation({
    mutationFn: async (tutor: string) =>
      unwrap(await api.POST("/api/v1/shortlists", { body: { job: jobId, tutor } })),
    onSuccess: refresh,
  });
  const offer = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/job-offer-batches", {
          body: { job: jobId, tutors: chosen, mode, expiry_hours: Number(expiry) || 24 },
        }),
      ),
    onSuccess: () => {
      setChosen([]);
      refresh();
    },
  });
  const post = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/job-postings", { body: { job: jobId, title: "", min_score: "0" } }),
      ),
    onSuccess: refresh,
  });
  const slots = (job.data?.default_schedule ?? []) as { weekday: number; time: string }[];
  const toggle = (id: string) =>
    setChosen((current) =>
      current.includes(id) ? current.filter((c) => c !== id) : [...current, id],
    );
  const openPosting = postings.data?.results.find((p) => p.status === "open");
  return (
    <div className="space-y-4">
      <p className="text-sm">
        <Link to="/jobs/$jobId" params={{ jobId }} className={linkClass}>
          {job.data?.name ?? t("jobs.title")}
        </Link>
      </p>
      <h1 className="text-2xl font-semibold">{t("matching.findTutor")}</h1>
      {canRestricted ? (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeRestricted}
            onChange={(e) => setIncludeRestricted(e.target.checked)}
          />
          {t("matching.includeRestricted")}
        </label>
      ) : null}
      {results.error ? <Alert tone="danger">{results.error.message}</Alert> : null}
      {results.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      {results.data ? (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <Card title={t("matching.results", { count: results.data.results.length })}>
            {results.data.results.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("matching.none")}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-muted-foreground">
                      {canOffer ? <th scope="col">{t("matching.offer")}</th> : null}
                      <th scope="col">#</th>
                      <th scope="col">{t("matching.tutor")}</th>
                      <th scope="col">{t("matching.score")}</th>
                      <th scope="col">{t("matching.distance")}</th>
                      <th scope="col">{t("matching.availability")}</th>
                      <th scope="col">
                        <span className="sr-only">{t("matching.actions")}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.data.results.map((row) => (
                      <tr key={row.tutor.id} className="border-t border-border align-top">
                        {canOffer ? (
                          <td>
                            <input
                              type="checkbox"
                              aria-label={t("matching.choose", { name: row.tutor.name })}
                              checked={chosen.includes(row.tutor.id)}
                              disabled={row.restricted}
                              onChange={() => toggle(row.tutor.id)}
                            />
                          </td>
                        ) : null}
                        <td>{row.rank}</td>
                        <td>
                          <Link
                            to="/tutors/$tutorId"
                            params={{ tutorId: row.tutor.id }}
                            className={linkClass}
                          >
                            {row.tutor.name}
                          </Link>
                          {row.restricted ? (
                            <span className="ml-1 rounded bg-red-100 px-1 text-xs text-red-800">
                              {t("matching.restricted")}
                            </span>
                          ) : null}
                          <Breakdown row={row} />
                        </td>
                        <td className="font-semibold">{row.score}</td>
                        <td>{row.distance_km === null ? "—" : `${row.distance_km} km`}</td>
                        <td>
                          <SlotFit fit={row.slot_fit} slots={slots} />
                        </td>
                        <td>
                          {canOffer && !row.shortlisted ? (
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => shortlist.mutate(row.tutor.id)}
                            >
                              {t("matching.shortlist")}
                            </Button>
                          ) : row.shortlisted ? (
                            <span className="text-xs">{t("matching.shortlisted")}</span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          <div className="space-y-4">
            <Card title={t("matching.map")}>
              <MatchMap origin={results.data.origin} rows={results.data.results} />
            </Card>
            {canOffer ? (
              <Card title={t("matching.sendOffers")}>
                <p className="text-sm">{t("matching.chosen", { count: chosen.length })}</p>
                <SelectField
                  label={t("matching.mode")}
                  value={mode}
                  onChange={(e) => setMode(e.target.value as typeof mode)}
                  options={[
                    { value: "sequential", label: t("matching.modes.sequential") },
                    { value: "simultaneous", label: t("matching.modes.simultaneous") },
                  ]}
                />
                <TextField
                  label={t("matching.expiryHours")}
                  type="number"
                  min={1}
                  value={expiry}
                  onChange={(e) => setExpiry(e.target.value)}
                />
                <Button
                  disabled={chosen.length === 0 || offer.isPending}
                  onClick={() => offer.mutate()}
                >
                  {t("matching.send")}
                </Button>
                {offer.error ? <Alert tone="danger">{offer.error.message}</Alert> : null}
              </Card>
            ) : null}
            {canPost ? (
              <Card title={t("matching.board")}>
                {openPosting ? (
                  <PostingPanel id={openPosting.id} onChange={refresh} />
                ) : (
                  <Button
                    variant="secondary"
                    onClick={() => post.mutate()}
                    disabled={post.isPending}
                  >
                    {t("matching.postJob")}
                  </Button>
                )}
                {post.error ? <Alert tone="danger">{post.error.message}</Alert> : null}
              </Card>
            ) : null}
          </div>
        </div>
      ) : null}
      {canOffer && batches.data?.results.length ? (
        <Card title={t("matching.offers")}>
          {batches.data.results.map((batch) => (
            <BatchPanel key={batch.id} batch={batch} onChange={refresh} />
          ))}
        </Card>
      ) : null}
    </div>
  );
}

function BatchPanel({ batch, onChange }: { batch: Batch; onChange: () => void }) {
  const { t, i18n } = useTranslation();
  const path = { params: { path: { id: batch.id } } };
  const cancel = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/job-offer-batches/{id}/cancel", path)),
    onSuccess: onChange,
  });
  const decide = useMutation({
    mutationFn: async (approve: boolean) =>
      unwrap(
        await api.POST("/api/v1/job-offer-batches/{id}/decide", {
          ...path,
          body: { approve, reason: "" },
        }),
      ),
    onSuccess: onChange,
  });
  const open = batch.status === "open" || batch.status === "awaiting_confirmation";
  return (
    <div className="space-y-2 border-t border-border pt-2 text-sm first:border-0 first:pt-0">
      <p>
        {t(`matching.modes.${batch.mode}`)} ·{" "}
        <strong>{t(`matching.batchStatus.${batch.status}`)}</strong> ·{" "}
        {formatDateTime(batch.created_at, i18n.language)}
      </p>
      <ol className="list-decimal pl-5">
        {batch.offers.map((o) => (
          <li key={o.id}>
            {o.tutor_name}: {t(`matching.offerStatus.${o.status}`)}
            {o.decline_reason ? ` (${o.decline_reason})` : ""}
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2">
        {batch.status === "awaiting_confirmation" ? (
          <>
            <Button size="sm" onClick={() => decide.mutate(true)}>
              {t("matching.confirm")}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => decide.mutate(false)}>
              {t("matching.reject")}
            </Button>
          </>
        ) : null}
        {open ? (
          <Button size="sm" variant="secondary" onClick={() => cancel.mutate()}>
            {t("matching.cancelOffers")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function PostingPanel({ id, onChange }: { id: string; onChange: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const posting = useQuery({
    queryKey: ["posting", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/job-postings/{id}", { params: { path: { id } } })),
  });
  const set = (data: Posting) => {
    queryClient.setQueryData(["posting", id], data);
    onChange();
  };
  const select = useMutation({
    mutationFn: async (app: string) =>
      unwrap(
        await api.POST("/api/v1/job-postings/{id}/applications/{app_id}/select", {
          params: { path: { id, app_id: app } },
        }),
      ),
    onSuccess: set,
  });
  const close = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/job-postings/{id}/close", { params: { path: { id } } })),
    onSuccess: set,
  });
  if (!posting.data) return <Spinner className="size-4" label={t("grid.loading")} />;
  const p = posting.data;
  return (
    <div className="space-y-2 text-sm">
      <p>{t("matching.posted", { eligible: p.eligible_count, applied: p.applications_count })}</p>
      <ul className="space-y-2">
        {p.applications.map((a) => (
          <li key={a.id} className="rounded border border-border p-2">
            <p className="font-medium">
              {a.tutor_name} · {a.score ?? "—"} · {t(`matching.applicationStatus.${a.status}`)}
            </p>
            {a.message ? <p className="text-muted-foreground">{a.message}</p> : null}
            {a.status === "applied" && p.status === "open" ? (
              <Button size="sm" onClick={() => select.mutate(a.id)}>
                {t("matching.select")}
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      {p.status === "open" ? (
        <Button size="sm" variant="secondary" onClick={() => close.mutate()}>
          {t("matching.closePosting")}
        </Button>
      ) : null}
      {select.error ? <Alert tone="danger">{select.error.message}</Alert> : null}
    </div>
  );
}

// --- cover, analytics, weights -------------------------------------------------------------

type Tab = "cover" | "analytics" | "weights";

/** Cover requests, matching analytics and weights (FR-19-4, FR-19-6). */
export function MatchingPage() {
  const { t } = useTranslation();
  const canCover = usePermission("matching.cover.manage");
  const canAnalytics = usePermission("matching.analytics.view");
  const canWeights = usePermission("matching.settings.manage");
  const tabs = [
    ...(canCover ? [{ key: "cover" as const, label: t("matching.cover") }] : []),
    ...(canAnalytics ? [{ key: "analytics" as const, label: t("matching.analytics") }] : []),
    ...(canWeights ? [{ key: "weights" as const, label: t("matching.weights") }] : []),
  ];
  const [tab, setTab] = useState<Tab>(tabs[0]?.key ?? "cover");
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("matching.title")}</h1>
      {tabs.length ? (
        <Tabs label={t("matching.title")} tabs={tabs} value={tab} onChange={setTab}>
          {tab === "cover" ? <CoverPanel /> : null}
          {tab === "analytics" ? <AnalyticsPanel /> : null}
          {tab === "weights" ? <WeightsPanel /> : null}
        </Tabs>
      ) : null}
    </div>
  );
}

function CoverPanel() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("open");
  const [open, setOpen] = useState<string | null>(null);
  const covers = useQuery({
    queryKey: ["cover-requests", status],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/cover-requests", { params: { query: { status } } })),
  });
  const cancel = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/cover-requests/{id}/cancel", { params: { path: { id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["cover-requests"] }),
  });
  return (
    <div className="space-y-3">
      <SelectField
        label={t("matching.status")}
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        options={["open", "filled", "unfilled", "cancelled"].map((s) => ({
          value: s,
          label: t(`matching.coverStatus.${s}`),
        }))}
      />
      {covers.data?.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("matching.noCover")}</p>
      ) : null}
      <ul className="space-y-2">
        {covers.data?.results.map((c: Cover) => (
          <li key={c.id} className="space-y-1 rounded-md border border-border p-3 text-sm">
            <p className="font-medium">
              {c.original_tutor_name} · {t(`matching.coverStatus.${c.status}`)}
              {c.accepted_by_name ? ` → ${c.accepted_by_name}` : ""}
            </p>
            <p className="text-muted-foreground">
              {c.lessons
                .map((l) => `${l.title} ${formatDateTime(l.start, i18n.language)}`)
                .join("; ")}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("matching.coverDeadline", { when: formatDateTime(c.deadline, i18n.language) })} ·{" "}
              {t("matching.notified", { count: c.notified_count })}
            </p>
            {c.status === "open" ? (
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setOpen(open === c.id ? null : c.id)}
                >
                  {t("matching.candidates")}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => cancel.mutate(c.id)}>
                  {t("matching.cancelCover")}
                </Button>
              </div>
            ) : null}
            {open === c.id ? <CoverCandidates id={c.id} /> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CoverCandidates({ id }: { id: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const rows = useQuery({
    queryKey: ["cover-candidates", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/cover-requests/{id}/candidates", { params: { path: { id } } })),
  });
  const assign = useMutation({
    mutationFn: async (tutor: string) =>
      unwrap(
        await api.POST("/api/v1/cover-requests/{id}/assign", {
          params: { path: { id } },
          body: { tutor },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["cover-requests"] }),
  });
  if (!rows.data) return <Spinner className="size-4" label={t("grid.loading")} />;
  if (rows.data.length === 0) return <p className="text-xs">{t("matching.none")}</p>;
  return (
    <ul className="space-y-1">
      {rows.data.map((row) => (
        <li key={row.tutor.id} className="flex items-center gap-2">
          <span>
            {row.tutor.name} · {row.score}
          </span>
          <Button size="sm" onClick={() => assign.mutate(row.tutor.id)}>
            {t("matching.assign")}
          </Button>
        </li>
      ))}
      {assign.error ? <Alert tone="danger">{assign.error.message}</Alert> : null}
    </ul>
  );
}

function AnalyticsPanel() {
  const { t } = useTranslation();
  const data = useQuery({
    queryKey: ["matching-analytics"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/matching/analytics", { params: { query: { days: 90 } } })),
  });
  if (!data.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const d = data.data;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title={t("matching.timeToMatch")}>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 text-sm">
          <dt>{t("matching.jobsMatched")}</dt>
          <dd>{d.time_to_match.jobs}</dd>
          <dt>{t("matching.averageHours")}</dt>
          <dd>{d.time_to_match.average_hours ?? "—"}</dd>
          <dt>{t("matching.medianHours")}</dt>
          <dd>{d.time_to_match.median_hours ?? "—"}</dd>
        </dl>
      </Card>
      <Card title={t("matching.acceptance")}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th scope="col">{t("matching.tutor")}</th>
              <th scope="col">{t("matching.sent")}</th>
              <th scope="col">{t("matching.accepted")}</th>
            </tr>
          </thead>
          <tbody>
            {d.offers.map((o) => (
              <tr key={o.tutor}>
                <td>{o.name}</td>
                <td>{o.sent}</td>
                <td>{Math.round(o.acceptance_rate * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title={t("matching.unmatched")}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th scope="col">{t("matching.subject")}</th>
              <th scope="col">{t("matching.area")}</th>
              <th scope="col">{t("matching.jobs")}</th>
              <th scope="col">{t("matching.oldestDays")}</th>
            </tr>
          </thead>
          <tbody>
            {d.unmatched.map((u) => (
              <tr key={`${u.subject}-${u.area}`}>
                <td>{u.subject || "—"}</td>
                <td>{u.area || "—"}</td>
                <td>{u.jobs}</td>
                <td>{u.oldest_days}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function WeightsPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const weights = useQuery({
    queryKey: ["matching-weights"],
    queryFn: async () => unwrap(await api.GET("/api/v1/matching/settings")),
  });
  const save = useMutation({
    mutationFn: async () => {
      const merged = Object.fromEntries(
        Object.entries(weights.data?.weights ?? {}).map(([k, v]) => [k, Number(draft[k] ?? v)]),
      );
      return unwrap(await api.PUT("/api/v1/matching/settings", { body: { weights: merged } }));
    },
    onSuccess: (data) => {
      setDraft({});
      queryClient.setQueryData(["matching-weights"], data);
    },
  });
  if (!weights.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  return (
    <form
      className="grid max-w-xl gap-3 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {Object.entries(weights.data.weights).map(([key, value]) => (
        <TextField
          key={key}
          label={t(`matching.factors.${key}`)}
          type="number"
          min={0}
          max={100}
          value={draft[key] ?? String(value)}
          onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
        />
      ))}
      <div className="sm:col-span-3">
        <Button type="submit" disabled={save.isPending}>
          {t("common.save")}
        </Button>
        {save.isSuccess ? <Alert tone="success">{t("matching.saved")}</Alert> : null}
        {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
      </div>
    </form>
  );
}
