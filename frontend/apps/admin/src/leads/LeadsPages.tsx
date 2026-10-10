import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type DragEvent, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { RecordActivity } from "../crm/Activity";

type Enquiry = components["schemas"]["Enquiry"];
type Stage = components["schemas"]["Stage"];

export function LeadsNav() {
  const { t } = useTranslation();
  const links = [
    { to: "/leads", label: t("leads.board") },
    { to: "/leads/waitlist", label: t("leads.waitlist") },
    { to: "/leads/forms", label: t("leads.forms") },
    { to: "/leads/reports", label: t("leads.reports") },
  ] as const;
  return (
    <nav aria-label={t("leads.title")} className="mb-4 flex flex-wrap gap-3 text-sm">
      {links.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          activeOptions={{ exact: true }}
          className="rounded-md px-2 py-1 hover:bg-muted [&.active]:font-medium"
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

export function LeadsPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <LeadsNav />
      {children}
    </div>
  );
}

function usePipelines() {
  return useQuery({
    queryKey: ["pipelines"],
    queryFn: async () => unwrap(await api.GET("/api/v1/pipelines")),
  });
}

/** Kanban board (FR-17-2): drag cards between stages, or use "Move to" from the keyboard. */
export function BoardPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("leads.enquiry.edit");
  const pipelines = usePipelines();
  const [pipeline, setPipeline] = useState("");
  const current = pipeline || pipelines.data?.[0]?.id || "";
  const board = useQuery({
    queryKey: ["enquiry-board", current],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/enquiries/board", {
          params: { query: current ? { pipeline: current } : {} },
        }),
      ),
    enabled: pipelines.isSuccess,
  });
  const move = useMutation({
    mutationFn: async ({ id, stage }: { id: string; stage: string }) =>
      unwrap(
        await api.POST("/api/v1/enquiries/{id}/move", {
          params: { path: { id } },
          body: { stage },
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["enquiry-board"] }),
  });
  const onDrop = (stage: string) => (e: DragEvent) => {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/enquiry");
    if (id) move.mutate({ id, stage });
  };
  const stages = board.data?.map((c) => c.stage) ?? [];
  return (
    <LeadsPage title={t("leads.title")}>
      <div className="flex flex-wrap items-end gap-3">
        {pipelines.data && pipelines.data.length > 1 ? (
          <label className="flex items-center gap-2 text-sm">
            <span>{t("leads.pipeline")}</span>
            <select
              className="h-9 rounded-md border border-border bg-background px-2"
              value={current}
              onChange={(e) => setPipeline(e.target.value)}
            >
              {pipelines.data.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <NewEnquiry />
      </div>
      {move.error ? <Alert tone="danger">{move.error.message}</Alert> : null}
      {board.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      <div className="flex gap-3 overflow-x-auto pb-2">
        {board.data?.map((column) => (
          <section
            key={column.stage.id}
            aria-label={column.stage.name}
            className="w-72 shrink-0 rounded-md bg-muted/50 p-2"
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop(column.stage.id!)}
          >
            <h2 className="mb-2 flex justify-between text-sm font-semibold">
              <span>{column.stage.name}</span>
              <span className="text-muted-foreground">{column.enquiries.length}</span>
            </h2>
            <ul className="space-y-2">
              {column.enquiries.map((enquiry) => (
                <Card
                  key={enquiry.id}
                  enquiry={enquiry}
                  stages={stages}
                  canEdit={canEdit}
                  onMove={(stage) => move.mutate({ id: enquiry.id, stage })}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </LeadsPage>
  );
}

function Card({
  enquiry,
  stages,
  canEdit,
  onMove,
}: {
  enquiry: Enquiry;
  stages: Stage[];
  canEdit: boolean;
  onMove: (stage: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <li
      draggable={canEdit}
      onDragStart={(e) => e.dataTransfer.setData("text/enquiry", enquiry.id)}
      className="space-y-1 rounded-md border border-border bg-background p-2 text-sm"
    >
      <Link to="/leads/$id" params={{ id: enquiry.id }} className="font-medium underline">
        {enquiry.title}
      </Link>
      <p className="text-xs text-muted-foreground">
        {enquiry.student_names.join(", ")}
        {enquiry.value_estimate ? ` · ${formatMoney(enquiry.value_estimate)}` : ""}
        {` · ${t("leads.age", { count: Math.floor(enquiry.age_hours / 24) })}`}
        {enquiry.owner_name ? ` · ${enquiry.owner_name}` : ""}
      </p>
      {enquiry.sla_breached ? (
        <p className="text-xs font-medium text-danger">{t("leads.slaBreached")}</p>
      ) : null}
      {canEdit ? (
        <label className="flex items-center gap-1 text-xs">
          <span className="sr-only">{t("leads.moveTo", { title: enquiry.title })}</span>
          <select
            aria-label={t("leads.moveTo", { title: enquiry.title })}
            className="h-7 rounded border border-border bg-background px-1"
            value={enquiry.stage}
            onChange={(e) => onMove(e.target.value)}
          >
            {stages.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </li>
  );
}

/** A phone or walk-in enquiry (FR-17-1 manual entry). */
function NewEnquiry() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canCreate = usePermission("leads.enquiry.create");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ first_name: "", last_name: "", email: "", phone: "",
                                     student: "", notes: "" }); // prettier-ignore
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/enquiries", {
          body: {
            first_name: form.first_name,
            last_name: form.last_name,
            email: form.email,
            phone: form.phone,
            notes: form.notes,
            source: "phone",
            priority: "normal",
            students: form.student ? [{ first_name: form.student }] : [],
          },
        }),
      ),
    onSuccess: () => {
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["enquiry-board"] });
    },
  });
  if (!canCreate) return null;
  if (!open) return <Button onClick={() => setOpen(true)}>{t("leads.newEnquiry")}</Button>;
  const field = (key: keyof typeof form, label: string) => (
    <TextField
      label={label}
      value={form[key]}
      onChange={(e) => setForm({ ...form, [key]: e.target.value })}
    />
  );
  return (
    <form
      aria-label={t("leads.newEnquiry")}
      className="grid w-full gap-2 rounded-md border border-border p-3 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      {field("first_name", t("leads.firstName"))}
      {field("last_name", t("leads.lastName"))}
      {field("email", t("leads.email"))}
      {field("phone", t("leads.phone"))}
      {field("student", t("leads.studentName"))}
      {field("notes", t("leads.notes"))}
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" loading={create.isPending}>
          {t("leads.add")}
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          {t("common.cancel")}
        </Button>
      </div>
      {create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
    </form>
  );
}

/** One enquiry: details, stage history, trial, convert or lose (FR-17-2..5). */
export function EnquiryPage({ id }: { id: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const enquiry = useQuery({
    queryKey: ["enquiry", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/enquiries/{id}", { params: { path: { id } } })),
  });
  const history = useQuery({
    queryKey: ["enquiry", id, "history"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/enquiries/{id}/history", { params: { path: { id } } })),
  });
  const refresh = (data?: Enquiry) => {
    if (data) queryClient.setQueryData(["enquiry", id], data);
    void queryClient.invalidateQueries({ queryKey: ["enquiry", id, "history"] });
  };
  if (!enquiry.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const e = enquiry.data;
  return (
    <LeadsPage title={e.title}>
      <p className="text-sm">
        {e.stage_name} · {t(`leads.status.${e.status}`)} · {t(`leads.sources.${e.source}`)}
        {e.source_detail ? ` (${e.source_detail})` : ""} · {formatDate(e.created_at)}
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="space-y-1 rounded-md border border-border p-4 text-sm">
          <h2 className="font-semibold">{t("leads.contact")}</h2>
          <p>
            <Link to="/clients/$clientId" params={{ clientId: e.client }} className="underline">
              {e.contact_name || e.client_name}
            </Link>
          </p>
          <p>{[e.contact_email, e.contact_phone].filter(Boolean).join(" · ")}</p>
          <p>
            {t("leads.students")}: {e.student_names.join(", ") || "–"}
          </p>
          <p>
            {t("leads.subjects")}:{" "}
            {(e.subjects as { subject: string }[]).map((s) => s.subject).join(", ") || "–"}
          </p>
          {e.notes ? <p className="whitespace-pre-line">{e.notes}</p> : null}
          {e.trial_outcome ? (
            <p>
              {t("leads.trialOutcome")}: {t(`leads.outcomes.${e.trial_outcome}`)}
            </p>
          ) : null}
        </section>
        <section className="space-y-2 rounded-md border border-border p-4 text-sm">
          <h2 className="font-semibold">{t("leads.history")}</h2>
          <ol className="space-y-1">
            {history.data?.map((h) => (
              <li key={h.id}>
                {formatDateTime(h.created_at)} · {h.to_stage_name}
              </li>
            ))}
          </ol>
        </section>
      </div>
      {e.status === "open" ? <EnquiryActions enquiry={e} onDone={refresh} /> : null}
      <RecordActivity target={{ target_type: "leads.enquiry", target_id: id }} />
    </LeadsPage>
  );
}

function EnquiryActions({ enquiry, onDone }: { enquiry: Enquiry; onDone: (e: Enquiry) => void }) {
  const { t } = useTranslation();
  const canConvert = usePermission("leads.enquiry.convert");
  const [reason, setReason] = useState("");
  const [service, setService] = useState("");
  const [invite, setInvite] = useState(true);
  const [trialStart, setTrialStart] = useState("");
  const [outcome, setOutcome] = useState<"continuing" | "not_continuing" | "undecided">(
    "continuing",
  );
  const settings = useQuery({
    queryKey: ["settings", "leads"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/settings/{area}", { params: { path: { area: "leads" } } })),
  });
  const services = useQuery({
    queryKey: ["services"],
    queryFn: async () => unwrap(await api.GET("/api/v1/catalogue/services")),
  });
  const path = { params: { path: { id: enquiry.id } } };
  const lose = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/enquiries/{id}/lose", {
          ...path,
          body: { reason, nurture: false },
        }),
      ),
    onSuccess: onDone,
  });
  const convert = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/enquiries/{id}/convert", {
          ...path,
          body: { jobs: [{ service }], invite_to_portal: invite, payment_setup_link: false },
        }),
      ),
    onSuccess: (r) => onDone(r.enquiry),
  });
  const trial = useMutation({
    mutationFn: async () => {
      const start = new Date(trialStart);
      const end = new Date(start.getTime() + 60 * 60_000);
      return unwrap(
        await api.POST("/api/v1/enquiries/{id}/trial", {
          ...path,
          body: {
            start: start.toISOString(),
            end: end.toISOString(),
            service,
            price: { amount: "0", currency: enquiry.value_estimate?.currency ?? "GBP" },
          },
        }),
      );
    },
    onSuccess: onDone,
  });
  const recordOutcome = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/enquiries/{id}/trial-outcome", { ...path, body: { outcome } }),
      ),
    onSuccess: onDone,
  });
  const reasons = (settings.data?.values["leads.lost_reasons"] as string[] | undefined) ?? [];
  const error = lose.error ?? convert.error ?? trial.error ?? recordOutcome.error;
  return (
    <section
      aria-labelledby="enquiry-actions"
      className="space-y-3 rounded-md border border-border p-4"
    >
      <h2 id="enquiry-actions" className="font-semibold">
        {t("leads.actions")}
      </h2>
      <label className="flex flex-wrap items-center gap-2 text-sm">
        <span>{t("leads.service")}</span>
        <select
          className="h-9 rounded-md border border-border bg-background px-2"
          value={service}
          onChange={(e) => setService(e.target.value)}
        >
          <option value="">{t("leads.chooseService")}</option>
          {services.data?.results.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      {!enquiry.trial_lesson ? (
        <div className="flex flex-wrap items-end gap-2">
          <TextField
            label={t("leads.trialStart")}
            type="datetime-local"
            value={trialStart}
            onChange={(e) => setTrialStart(e.target.value)}
          />
          <Button
            variant="secondary"
            disabled={!service || !trialStart}
            onClick={() => trial.mutate()}
          >
            {t("leads.bookFreeTrial")}
          </Button>
        </div>
      ) : !enquiry.trial_outcome ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex items-center gap-2 text-sm">
            <span>{t("leads.trialOutcome")}</span>
            <select
              className="h-9 rounded-md border border-border bg-background px-2"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value as typeof outcome)}
            >
              {(["continuing", "not_continuing", "undecided"] as const).map((o) => (
                <option key={o} value={o}>
                  {t(`leads.outcomes.${o}`)}
                </option>
              ))}
            </select>
          </label>
          <Button variant="secondary" onClick={() => recordOutcome.mutate()}>
            {t("leads.saveOutcome")}
          </Button>
        </div>
      ) : null}
      {canConvert ? (
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={invite} onChange={(e) => setInvite(e.target.checked)} />
            {t("leads.invitePortal")}
          </label>
          <Button disabled={!service} onClick={() => convert.mutate()} loading={convert.isPending}>
            {t("leads.convert")}
          </Button>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm">
          <span>{t("leads.lostReason")}</span>
          <select
            className="h-9 rounded-md border border-border bg-background px-2"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          >
            <option value="">{t("leads.chooseReason")}</option>
            {reasons.map((r) => (
              <option key={r} value={r}>
                {t(`leads.lostReasons.${r}`, { defaultValue: r })}
              </option>
            ))}
          </select>
        </label>
        <Button variant="ghost" disabled={!reason} onClick={() => lose.mutate()}>
          {t("leads.markLost")}
        </Button>
      </div>
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
    </section>
  );
}
