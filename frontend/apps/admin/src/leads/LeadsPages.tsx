import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FactList,
  NamePlate,
  PageHeader,
  Panel,
  PanelRow,
  PanelRows,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type DragEvent, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { AiEnquiryExtract, AiEnquiryTriage } from "../ai/AiWidgets";
import { AttachedFiles } from "../components/AttachedFiles";
import { RecordHeader, RecordLayout } from "../components/RecordHeader";
import { RecordActivity } from "../crm/Activity";
import { ProposalsSection } from "./ProposalPages";

type Enquiry = components["schemas"]["Enquiry"];
type Stage = components["schemas"]["Stage"];

/** The enquiries area's own pages, as a row of links ruled like tabs. */
export function LeadsNav() {
  const { t } = useTranslation();
  const links = [
    { to: "/leads", label: t("leads.board") },
    { to: "/leads/waitlist", label: t("leads.waitlist") },
    { to: "/leads/forms", label: t("leads.forms") },
    { to: "/leads/reports", label: t("leads.reports") },
  ] as const;
  return (
    <nav
      aria-label={t("leads.title")}
      className="mb-6 flex gap-1 overflow-x-auto border-b border-border [scrollbar-width:none]"
    >
      {links.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          activeOptions={{ exact: true }}
          className="-mb-px shrink-0 border-b-2 border-transparent px-3 py-2 text-sm whitespace-nowrap text-muted-foreground hover:text-foreground [&.active]:border-foreground [&.active]:font-semibold [&.active]:text-foreground"
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

export function LeadsPage({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <PageHeader title={title} description={description} actions={actions} className="mb-4" />
      <LeadsNav />
      <div className="space-y-6">{children}</div>
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
  const canCreate = usePermission("leads.enquiry.create");
  const [adding, setAdding] = useState(false);
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
    <LeadsPage
      title={t("leads.title")}
      actions={
        canCreate && !adding ? (
          <Button onClick={() => setAdding(true)}>{t("leads.newEnquiry")}</Button>
        ) : null
      }
    >
      {adding ? <NewEnquiry onClose={() => setAdding(false)} /> : null}
      {pipelines.data && pipelines.data.length > 1 ? (
        <div className="flex flex-wrap items-center gap-2">
          <SelectField
            label={t("leads.pipeline")}
            hideLabel
            size="sm"
            value={current}
            onChange={(e) => setPipeline(e.target.value)}
            options={pipelines.data.map((p) => ({ value: p.id ?? "", label: p.name }))}
          />
        </div>
      ) : null}
      {move.error ? <Alert tone="danger">{move.error.message}</Alert> : null}
      {board.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {/* Scrolls sideways when the stages outgrow the page: focusable so keyboards can scroll it. */}
      <div
        role="region"
        aria-label={t("leads.board")}
        tabIndex={0}
        className="flex items-start gap-4 overflow-x-auto pb-2"
      >
        {board.data?.map((column) => (
          <section
            key={column.stage.id}
            aria-label={column.stage.name}
            className="w-72 shrink-0 rounded-xl border border-border bg-surface"
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop(column.stage.id!)}
          >
            <h2 className="flex items-baseline justify-between gap-2 border-b border-border px-4 py-3 text-base font-semibold">
              <span className="min-w-0 truncate">{column.stage.name}</span>
              <span className="text-sm font-normal text-muted-foreground tabular-nums">
                {column.enquiries.length}
              </span>
            </h2>
            {column.enquiries.length ? (
              <ul className="divide-y divide-rule">
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
            ) : (
              <p className="px-4 py-4 text-sm text-muted-foreground">{t("designS5.leads.empty")}</p>
            )}
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
      className="space-y-1.5 px-4 py-2.5 text-sm hover:bg-muted/60"
    >
      <NamePlate
        name={
          <Link
            to="/leads/$id"
            params={{ id: enquiry.id }}
            className="underline-offset-2 hover:underline"
          >
            {enquiry.title}
          </Link>
        }
        context={[
          enquiry.student_names.join(", "),
          enquiry.value_estimate ? formatMoney(enquiry.value_estimate) : "",
          t("leads.age", { count: Math.floor(enquiry.age_hours / 24) }),
          enquiry.owner_name,
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      {enquiry.sla_breached ? (
        <p className="text-xs font-semibold text-margin">{t("leads.slaBreached")}</p>
      ) : null}
      {canEdit ? (
        <select
          aria-label={t("leads.moveTo", { title: enquiry.title })}
          className="h-8 w-full rounded-md border border-field bg-surface px-2 text-sm"
          value={enquiry.stage}
          onChange={(e) => onMove(e.target.value)}
        >
          {stages.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      ) : null}
    </li>
  );
}

/** A phone or walk-in enquiry (FR-17-1 manual entry). */
function NewEnquiry({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
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
      onClose();
      void queryClient.invalidateQueries({ queryKey: ["enquiry-board"] });
    },
  });
  const field = (key: keyof typeof form, label: string) => (
    <TextField
      label={label}
      value={form[key]}
      onChange={(e) => setForm({ ...form, [key]: e.target.value })}
    />
  );
  return (
    <Panel title={t("leads.newEnquiry")} className="max-w-4xl">
      <form
        aria-label={t("leads.newEnquiry")}
        className="grid gap-4 sm:grid-cols-3"
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
        <AiEnquiryExtract
          onExtract={(x) =>
            setForm((f) => ({
              first_name: x.contact.first_name || f.first_name,
              last_name: x.contact.last_name || f.last_name,
              email: x.contact.email || f.email,
              phone: x.contact.phone || f.phone,
              student: x.students[0]?.first_name || f.student,
              notes: [
                f.notes,
                x.summary,
                x.subjects.map((s) => `${s.subject} ${s.level}`.trim()).join(", "),
                x.availability.join("; "),
                [x.location.area, x.location.postcode, x.location.mode].filter(Boolean).join(", "),
              ]
                .filter(Boolean)
                .join("\n"),
            }))
          }
        />
        <div className="flex gap-2 sm:col-span-3">
          <Button type="submit" loading={create.isPending}>
            {t("leads.add")}
          </Button>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
        </div>
        {create.error ? (
          <Alert tone="danger" className="sm:col-span-3">
            {create.error.message}
          </Alert>
        ) : null}
      </form>
    </Panel>
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
  if (!enquiry.data) return <Spinner label={t("grid.loading")} />;
  const e = enquiry.data;
  const subjects = (e.subjects as { subject: string }[]).map((s) => s.subject).join(", ");
  return (
    <article>
      <RecordHeader
        back={<Link to="/leads">{t("leads.title")}</Link>}
        title={e.title}
        description={[
          e.stage_name,
          t(`leads.status.${e.status}`),
          `${t(`leads.sources.${e.source}`)}${e.source_detail ? ` (${e.source_detail})` : ""}`,
          formatDate(e.created_at),
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      <RecordLayout
        main={
          <>
            {e.status === "open" ? (
              <AiEnquiryTriage
                enquiryId={id}
                onApplied={() => void queryClient.invalidateQueries({ queryKey: ["enquiry", id] })}
              />
            ) : null}
            {e.status === "open" ? <EnquiryActions enquiry={e} onDone={refresh} /> : null}
            <ProposalsSection enquiryId={id} />
            <RecordActivity target={{ target_type: "leads.enquiry", target_id: id }} />
          </>
        }
        side={
          <>
            <Panel title={t("leads.contact")} flush>
              <div className="px-5 py-2.5 text-sm">
                <NamePlate
                  name={
                    <Link
                      to="/clients/$clientId"
                      params={{ clientId: e.client }}
                      className="underline-offset-2 hover:underline"
                    >
                      {e.contact_name || e.client_name}
                    </Link>
                  }
                  context={[e.contact_email, e.contact_phone].filter(Boolean).join(" · ")}
                />
              </div>
              <FactList
                className="border-t border-rule"
                empty="–"
                items={[
                  [t("leads.students"), e.student_names.join(", ")],
                  [t("leads.subjects"), subjects],
                  ...(e.trial_outcome
                    ? ([
                        [t("leads.trialOutcome"), t(`leads.outcomes.${e.trial_outcome}`)],
                      ] as [string, string][])
                    : []),
                ]}
              />
              {e.notes ? (
                <p className="border-t border-rule px-5 py-2.5 text-sm whitespace-pre-line">
                  {e.notes}
                </p>
              ) : null}
              {e.attachments?.length ? (
                <div className="border-t border-rule px-5 py-2.5 text-sm">
                  <AttachedFiles files={e.attachments} label={t("hiring.files.attachments")} />
                </div>
              ) : null}
            </Panel>
            <Panel title={t("leads.history")} flush>
              {history.data?.length ? (
                <PanelRows>
                  {history.data.map((h) => (
                    <PanelRow key={h.id}>
                      <span className="block">{h.to_stage_name}</span>
                      <time dateTime={h.created_at} className="block text-xs text-muted-foreground">
                        {formatDateTime(h.created_at)}
                      </time>
                    </PanelRow>
                  ))}
                </PanelRows>
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  {history.isPending ? t("grid.loading") : t("designS5.leads.noHistory")}
                </p>
              )}
            </Panel>
          </>
        }
      />
    </article>
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
  const row = "flex flex-wrap items-end gap-3 px-5 py-4";
  return (
    <Panel title={t("leads.actions")} flush>
      <div className="divide-y divide-rule">
        <div className={row}>
          <div className="min-w-56 flex-1 sm:max-w-sm">
            <SelectField
              label={t("leads.service")}
              value={service}
              onChange={(e) => setService(e.target.value)}
              options={[
                { value: "", label: t("leads.chooseService") },
                ...(services.data?.results ?? []).map((s) => ({ value: s.id, label: s.name })),
              ]}
            />
          </div>
        </div>
        {!enquiry.trial_lesson ? (
          <div className={row}>
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
          <div className={row}>
            <SelectField
              label={t("leads.trialOutcome")}
              value={outcome}
              onChange={(e) => setOutcome(e.target.value as typeof outcome)}
              options={(["continuing", "not_continuing", "undecided"] as const).map((o) => ({
                value: o,
                label: t(`leads.outcomes.${o}`),
              }))}
            />
            <Button variant="secondary" onClick={() => recordOutcome.mutate()}>
              {t("leads.saveOutcome")}
            </Button>
          </div>
        ) : null}
        {canConvert ? (
          <div className="flex flex-wrap items-center gap-3 px-5 py-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={invite}
                onChange={(e) => setInvite(e.target.checked)}
              />
              {t("leads.invitePortal")}
            </label>
            <Button disabled={!service} onClick={() => convert.mutate()} loading={convert.isPending}>
              {t("leads.convert")}
            </Button>
          </div>
        ) : null}
        <div className={row}>
          <SelectField
            label={t("leads.lostReason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            options={[
              { value: "", label: t("leads.chooseReason") },
              ...reasons.map((r) => ({
                value: r,
                label: t(`leads.lostReasons.${r}`, { defaultValue: r }),
              })),
            ]}
          />
          <Button variant="ghost" disabled={!reason} onClick={() => lose.mutate()}>
            {t("leads.markLost")}
          </Button>
        </div>
        {error ? (
          <div className="px-5 py-4">
            <Alert tone="danger">{error.message}</Alert>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
