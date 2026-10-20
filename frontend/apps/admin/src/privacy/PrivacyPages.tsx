import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
import {
  AreaSettings,
  Cell,
  FormCard,
  PersonPicker,
  Table,
  TextArea,
  type PersonRef,
} from "./shared";
import { daysUntil, PAGE } from "./util";

type DataRequest = components["schemas"]["DataRequest"];
type Hold = components["schemas"]["LegalHold"];
type Policy = components["schemas"]["RetentionPolicy"];
type Run = components["schemas"]["RetentionRun"];
type Redaction = { section?: string; record_id?: string; record_field?: string; file_id?: string };

const TABS = [
  { key: "requests", permission: "privacy.dsar.manage" },
  { key: "erasures", permission: "privacy.dsar.manage" },
  { key: "holds", permission: "privacy.legal_hold.manage" },
  { key: "retention", permission: "privacy.retention.manage" },
  { key: "agreement", permission: "privacy.dpa.manage" },
  { key: "settings", permission: "org.settings.view" },
] as const;
type Tab = (typeof TABS)[number]["key"];

const link = "text-primary underline-offset-2 hover:underline";

/** The Privacy centre (E29 Part 2): data subject requests, erasures, legal holds,
 * retention, the data processing agreement and privacy settings. */
export function PrivacyPage() {
  const { t } = useTranslation();
  const allowed: Record<string, boolean> = {
    "privacy.dsar.manage": usePermission("privacy.dsar.manage"),
    "privacy.legal_hold.manage": usePermission("privacy.legal_hold.manage"),
    "privacy.retention.manage": usePermission("privacy.retention.manage"),
    "privacy.dpa.manage": usePermission("privacy.dpa.manage"),
    "org.settings.view": usePermission("org.settings.view"),
  };
  const tabs = TABS.filter((tab) => allowed[tab.permission]);
  const [tab, setTab] = useState<Tab>(tabs[0]?.key ?? "requests");
  if (!tabs.length) return <Alert tone="danger">{t("privacyCentre.forbidden")}</Alert>;
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">{t("privacyCentre.title")}</h1>
      <Tabs
        label={t("privacyCentre.title")}
        tabs={tabs.map(({ key }) => ({ key, label: t(`privacyCentre.tabs.${key}`) }))}
        value={tab}
        onChange={setTab}
      >
        {tab === "requests" ? <RequestsSection /> : null}
        {tab === "erasures" ? <ErasuresSection /> : null}
        {tab === "holds" ? <HoldsSection /> : null}
        {tab === "retention" ? <RetentionSection /> : null}
        {tab === "agreement" ? <AgreementSection /> : null}
        {tab === "settings" ? (
          <AreaSettings area="privacy" label={t("privacyCentre.tabs.settings")} />
        ) : null}
      </Tabs>
    </section>
  );
}

// --- requests (T05) -----------------------------------------------------------------------------

function DueBadge({ request }: { request: DataRequest }) {
  const { t } = useTranslation();
  if (request.closed_at) return null;
  const days = daysUntil(request.due_at);
  const tone =
    days < 0 ? "text-destructive font-semibold" : days <= 7 ? "text-warning" : "text-foreground";
  return (
    <span className={tone}>
      {days < 0
        ? t("privacyCentre.overdueBy", { count: -days })
        : t("privacyCentre.dueIn", { count: days })}
    </span>
  );
}

function RequestsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState("true");
  const requests = useQuery({
    queryKey: ["data-requests", open],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/data-requests", {
          params: { query: { ...PAGE, ...(open ? { open: open === "true" } : {}) } },
        }),
      ),
  });
  const [person, setPerson] = useState<PersonRef | null>(null);
  const [form, setForm] = useState({
    kind: "access",
    requester_name: "",
    requester_email: "",
    relationship: "self",
    channel: "email",
    details: "",
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/data-requests", {
          body: {
            ...form,
            kind: form.kind as "access",
            relationship: form.relationship as "self",
            channel: form.channel as "email",
            subject_type: person?.subject_type ?? "",
            subject_id: person?.subject_id ?? "",
          },
        }),
      ),
    onSuccess: () => {
      setPerson(null);
      setForm({ ...form, requester_name: "", requester_email: "", details: "" });
      void queryClient.invalidateQueries({ queryKey: ["data-requests"] });
    },
  });
  const errors = fieldErrors(create.error);
  return (
    <div className="space-y-6">
      <SelectField
        label={t("privacyCentre.show")}
        value={open}
        onChange={(e) => setOpen(e.target.value)}
        options={[
          { value: "true", label: t("privacyCentre.openRequests") },
          { value: "false", label: t("privacyCentre.closedRequests") },
          { value: "", label: t("privacyCentre.allRequests") },
        ]}
      />
      {requests.data ? (
        <Table
          caption={t("privacyCentre.requests")}
          headers={[
            t("privacyCentre.reference"),
            t("privacyCentre.kind"),
            t("privacyCentre.person"),
            t("privacyCentre.status"),
            t("privacyCentre.received"),
            t("privacyCentre.deadline"),
          ]}
        >
          {requests.data.results.map((r) => (
            <tr key={r.id}>
              <Cell>
                <Link
                  to="/privacy/requests/$requestId"
                  params={{ requestId: r.id }}
                  className={link}
                >
                  {r.reference}
                </Link>
              </Cell>
              <Cell>{t(`privacyCentre.kinds.${r.kind}`)}</Cell>
              <Cell>{r.subject_label || r.requester_name}</Cell>
              <Cell>{t(`privacyCentre.statuses.${r.status}`)}</Cell>
              <Cell>{formatDate(r.received_at, i18n.language)}</Cell>
              <Cell>
                {formatDate(r.due_at, i18n.language)} <DueBadge request={r} />
              </Cell>
            </tr>
          ))}
        </Table>
      ) : (
        <Spinner label={t("grid.loading")} />
      )}
      <FormCard
        title={t("privacyCentre.logRequest")}
        submit={t("privacyCentre.logRequestSubmit")}
        pending={create.isPending}
        error={create.error}
        onSubmit={() => create.mutate()}
      >
        <PersonPicker value={person} onChange={setPerson} />
        <SelectField
          label={t("privacyCentre.kind")}
          value={form.kind}
          onChange={(e) => setForm({ ...form, kind: e.target.value })}
          options={["access", "portability", "erasure"].map((k) => ({
            value: k,
            label: t(`privacyCentre.kinds.${k}`),
          }))}
        />
        <SelectField
          label={t("privacyCentre.channel")}
          value={form.channel}
          onChange={(e) => setForm({ ...form, channel: e.target.value })}
          options={["email", "phone", "letter", "in_person", "portal"].map((k) => ({
            value: k,
            label: t(`privacyCentre.channels.${k}`),
          }))}
        />
        <TextField
          label={t("privacyCentre.requesterName")}
          required
          value={form.requester_name}
          error={errors.requester_name}
          onChange={(e) => setForm({ ...form, requester_name: e.target.value })}
        />
        <TextField
          label={t("privacyCentre.requesterEmail")}
          type="email"
          hint={t("privacyCentre.requesterEmailHint")}
          value={form.requester_email}
          error={errors.requester_email}
          onChange={(e) => setForm({ ...form, requester_email: e.target.value })}
        />
        <SelectField
          label={t("privacyCentre.relationship")}
          value={form.relationship}
          onChange={(e) => setForm({ ...form, relationship: e.target.value })}
          options={["self", "parent", "representative"].map((k) => ({
            value: k,
            label: t(`privacyCentre.relationships.${k}`),
          }))}
        />
        <TextArea
          label={t("privacyCentre.details")}
          value={form.details}
          onChange={(details) => setForm({ ...form, details })}
        />
      </FormCard>
    </div>
  );
}

function useRequest(requestId: string) {
  return useQuery({
    queryKey: ["data-requests", "detail", requestId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/data-requests/{id}", { params: { path: { id: requestId } } })),
  });
}

/** One request: identity checks, deadline, the export review (redaction) or the erasure
 * approval, and what the erasure did. */
export function DataRequestPage({ requestId }: { requestId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const request = useRequest(requestId);
  const refresh = (data: DataRequest) =>
    queryClient.setQueryData(["data-requests", "detail", requestId], data);
  const verify = useMutation({
    mutationFn: async (checks: Record<string, boolean>) =>
      unwrap(
        await api.POST("/api/v1/data-requests/{id}/verify", {
          params: { path: { id: requestId } },
          body: { checks },
        }),
      ),
    onSuccess: refresh,
  });
  const [extendDays, setExtendDays] = useState(30);
  const [reason, setReason] = useState("");
  const extend = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/data-requests/{id}/extend", {
          params: { path: { id: requestId } },
          body: { days: extendDays, reason },
        }),
      ),
    onSuccess: refresh,
  });
  const reject = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/data-requests/{id}/reject", {
          params: { path: { id: requestId } },
          body: { reason },
        }),
      ),
    onSuccess: refresh,
  });
  if (!request.data) return <Spinner label={t("grid.loading")} />;
  const r = request.data;
  return (
    <article className="space-y-6">
      <p className="text-sm">
        <Link to="/privacy" className={link}>
          {t("privacyCentre.title")}
        </Link>
      </p>
      <header>
        <h1 className="text-2xl font-semibold">
          {r.reference} · {t(`privacyCentre.kinds.${r.kind}`)}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t(`privacyCentre.statuses.${r.status}`)} ·{" "}
          {t("privacyCentre.dueOn", { date: formatDate(r.due_at, i18n.language) })}{" "}
          <DueBadge request={r} />
        </p>
      </header>
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="font-medium">{t("privacyCentre.person")}</dt>
          <dd>
            {r.subject_label} ({t(`privacyCentre.subjectTypes.${r.subject_type}`)})
          </dd>
        </div>
        <div>
          <dt className="font-medium">{t("privacyCentre.requester")}</dt>
          <dd>
            {r.requester_name} {r.requester_email ? `<${r.requester_email}>` : ""} ·{" "}
            {t(`privacyCentre.relationships.${r.relationship}`)}
          </dd>
        </div>
        <div>
          <dt className="font-medium">{t("privacyCentre.received")}</dt>
          <dd>
            {formatDateTime(r.received_at, i18n.language)} ·{" "}
            {t(`privacyCentre.channels.${r.channel}`)}
          </dd>
        </div>
        {r.details ? (
          <div className="sm:col-span-2">
            <dt className="font-medium">{t("privacyCentre.details")}</dt>
            <dd className="whitespace-pre-wrap">{r.details}</dd>
          </div>
        ) : null}
      </dl>

      <section aria-labelledby="checks" className="rounded-md border border-border p-4">
        <h2 id="checks" className="mb-2 font-semibold">
          {t("privacyCentre.verification")}
        </h2>
        <ul className="space-y-1">
          {r.checklist.map((c) => (
            <li key={c.key}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={c.done}
                  disabled={!!r.closed_at || verify.isPending}
                  onChange={(e) => verify.mutate({ [c.key]: e.target.checked })}
                />
                {c.title}
                {c.is_required ? "" : ` (${t("privacyCentre.optional")})`}
              </label>
            </li>
          ))}
        </ul>
        {r.verified_at ? (
          <p role="status" className="mt-2 text-sm">
            {t("privacyCentre.verifiedOn", {
              date: formatDateTime(r.verified_at, i18n.language),
            })}
          </p>
        ) : null}
        {verify.error ? <Alert tone="danger">{verify.error.message}</Alert> : null}
      </section>

      {r.status === "in_review" && r.kind !== "erasure" ? <ExportReview request={r} /> : null}
      {r.kind === "erasure" ? <ErasureReview request={r} /> : null}
      {r.delivered_at ? (
        <Alert tone="success">
          {t("privacyCentre.delivered", {
            date: formatDateTime(r.delivered_at, i18n.language),
            expires: r.link_expires_at ? formatDateTime(r.link_expires_at, i18n.language) : "",
            count: r.download_count,
          })}
        </Alert>
      ) : null}

      {!r.closed_at ? (
        <section aria-labelledby="manage" className="space-y-3 rounded-md border border-border p-4">
          <h2 id="manage" className="font-semibold">
            {t("privacyCentre.manage")}
          </h2>
          <TextArea
            label={t("privacyCentre.reason")}
            value={reason}
            onChange={setReason}
            rows={2}
          />
          <div className="flex flex-wrap items-end gap-2">
            <TextField
              label={t("privacyCentre.extendDays")}
              type="number"
              min={1}
              max={60}
              value={String(extendDays)}
              onChange={(e) => setExtendDays(Number(e.target.value))}
            />
            <Button variant="secondary" onClick={() => extend.mutate()} disabled={!reason}>
              {t("privacyCentre.extend")}
            </Button>
            <Button variant="danger" onClick={() => reject.mutate()} disabled={!reason}>
              {t("privacyCentre.reject")}
            </Button>
          </div>
          {extend.error || reject.error ? (
            <Alert tone="danger">{(extend.error ?? reject.error)?.message}</Alert>
          ) : null}
        </section>
      ) : (
        <p className="text-sm text-muted-foreground">
          {t("privacyCentre.closedOn", {
            date: formatDateTime(r.closed_at, i18n.language),
          })}
          {r.close_reason ? ` · ${r.close_reason}` : ""}
        </p>
      )}
    </article>
  );
}

function ExportReview({ request }: { request: DataRequest }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const preview = useQuery({
    queryKey: ["data-requests", "preview", request.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/data-requests/{id}/export-preview", {
          params: { path: { id: request.id } },
        }),
      ),
  });
  const [redactions, setRedactions] = useState<Redaction[]>(
    (request.redactions as Redaction[] | undefined) ?? [],
  );
  const has = (r: Redaction) =>
    redactions.some(
      (x) =>
        x.section === r.section &&
        x.record_id === r.record_id &&
        x.file_id === r.file_id &&
        (x.record_field ?? undefined) === r.record_field,
    );
  const same = (x: Redaction, r: Redaction) =>
    x.section === r.section && x.record_id === r.record_id && x.file_id === r.file_id;
  const toggle = (r: Redaction) =>
    setRedactions(has(r) ? redactions.filter((x) => !same(x, r)) : [...redactions, r]);
  const approve = useMutation({
    mutationFn: async () => {
      unwrap(
        await api.PUT("/api/v1/data-requests/{id}/redactions", {
          params: { path: { id: request.id } },
          body: { redactions },
        }),
      );
      return unwrap(
        await api.POST("/api/v1/data-requests/{id}/approve-export", {
          params: { path: { id: request.id } },
        }),
      );
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["data-requests"] }),
  });
  if (!preview.data) return <Spinner label={t("grid.loading")} />;
  return (
    <section aria-labelledby="review" className="space-y-4 rounded-md border border-border p-4">
      <h2 id="review" className="font-semibold">
        {t("privacyCentre.reviewExport")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("privacyCentre.reviewExportHint")}</p>
      {preview.data.sections.map((section) => (
        <details key={section.key} className="rounded-md border border-border p-2">
          <summary className="cursor-pointer text-sm font-medium">
            {section.title} ({section.records.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {section.records.map((record) => {
              const id = String(record.id ?? "");
              const ref = { section: section.key, record_id: id };
              return (
                <li key={id} className="rounded bg-muted/40 p-2 text-xs">
                  <label className="mb-1 flex items-center gap-2 font-medium">
                    <input type="checkbox" checked={has(ref)} onChange={() => toggle(ref)} />
                    {t("privacyCentre.redactRecord")}
                  </label>
                  <pre className="whitespace-pre-wrap break-words">
                    {JSON.stringify(record, null, 1)}
                  </pre>
                </li>
              );
            })}
          </ul>
        </details>
      ))}
      {preview.data.files.length ? (
        <fieldset className="text-sm">
          <legend className="font-medium">{t("privacyCentre.files")}</legend>
          {preview.data.files.map((f) => (
            <label key={f.id} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={has({ file_id: f.id })}
                onChange={() => toggle({ file_id: f.id })}
              />
              {t("privacyCentre.redactFile", { name: f.filename })}
            </label>
          ))}
        </fieldset>
      ) : null}
      {approve.error ? <Alert tone="danger">{approve.error.message}</Alert> : null}
      <Button onClick={() => approve.mutate()} disabled={approve.isPending}>
        {t("privacyCentre.approveExport", { count: redactions.length })}
      </Button>
    </section>
  );
}

function ErasureReview({ request }: { request: DataRequest }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const preview = (request.summary as { erasure?: components["schemas"]["ErasurePreview"] })
    .erasure;
  const record = useQuery({
    queryKey: ["data-requests", "erasure", request.id],
    enabled: ["completed", "blocked", "erasing"].includes(request.status),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/data-requests/{id}/erasure", {
          params: { path: { id: request.id } },
        }),
      ),
  });
  const approve = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/data-requests/{id}/approve-erasure", {
          params: { path: { id: request.id } },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["data-requests"] }),
  });
  return (
    <section aria-labelledby="erasure" className="space-y-3 rounded-md border border-border p-4">
      <h2 id="erasure" className="font-semibold">
        {t("privacyCentre.erasure")}
      </h2>
      {preview ? (
        <>
          <p className="text-sm">
            {t("privacyCentre.erasureCovers", {
              list: Object.entries(preview.subjects)
                .map(([k, n]) => `${n} × ${t(`privacyCentre.subjectTypes.${k}`)}`)
                .join(", "),
            })}
          </p>
          <p className="text-sm text-muted-foreground">
            {t("privacyCentre.financialKept", { years: preview.financial_retention_years })}
          </p>
          {preview.holds.length ? (
            <Alert tone="warning">{t("privacyCentre.heldWarning")}</Alert>
          ) : null}
        </>
      ) : null}
      {request.status === "in_review" ? (
        <>
          {approve.error ? <Alert tone="danger">{approve.error.message}</Alert> : null}
          <Button variant="danger" onClick={() => approve.mutate()} disabled={approve.isPending}>
            {t("privacyCentre.approveErasure")}
          </Button>
        </>
      ) : null}
      {record.data ? <ErasureReport record={record.data} locale={i18n.language} /> : null}
    </section>
  );
}

function ErasureReport({
  record,
  locale,
}: {
  record: components["schemas"]["ErasureRecord"];
  locale: string;
}) {
  const { t } = useTranslation();
  const report = record.report as Record<
    string,
    { anonymised?: number; deleted?: number; retained?: number; notes?: string[] }
  >;
  return (
    <Table
      caption={t("privacyCentre.erasureReport", {
        status: t(`privacyCentre.erasureStatuses.${record.status}`),
        date: record.completed_at ? formatDateTime(record.completed_at, locale) : "",
      })}
      headers={[
        t("privacyCentre.area"),
        t("privacyCentre.anonymised"),
        t("privacyCentre.deleted"),
        t("privacyCentre.retained"),
      ]}
    >
      {Object.entries(report)
        .filter(([, v]) => v && typeof v === "object" && "anonymised" in v)
        .map(([key, v]) => (
          <tr key={key}>
            <Cell>{key}</Cell>
            <Cell>{v.anonymised}</Cell>
            <Cell>{v.deleted}</Cell>
            <Cell>
              {v.retained}
              {v.notes?.length ? ` · ${v.notes.join("; ")}` : ""}
            </Cell>
          </tr>
        ))}
    </Table>
  );
}

function ErasuresSection() {
  const { t, i18n } = useTranslation();
  const erasures = useQuery({
    queryKey: ["erasures"],
    queryFn: async () => unwrap(await api.GET("/api/v1/erasures", { params: { query: PAGE } })),
  });
  if (!erasures.data) return <Spinner label={t("grid.loading")} />;
  return (
    <Table
      caption={t("privacyCentre.tabs.erasures")}
      headers={[
        t("privacyCentre.person"),
        t("privacyCentre.reasonCol"),
        t("privacyCentre.status"),
        t("privacyCentre.completed"),
        t("privacyCentre.financialUntil"),
      ]}
    >
      {erasures.data.results.map((e) => (
        <tr key={e.id}>
          <Cell>{(e.labels as Record<string, string>)[`${e.subject_type}:${e.subject_id}`]}</Cell>
          <Cell>{t(`privacyCentre.erasureReasons.${e.reason}`)}</Cell>
          <Cell>{t(`privacyCentre.erasureStatuses.${e.status}`)}</Cell>
          <Cell>{e.completed_at ? formatDateTime(e.completed_at, i18n.language) : ""}</Cell>
          <Cell>
            {e.financial_erased_at
              ? t("privacyCentre.financialErased")
              : e.financial_retained_until
                ? formatDate(e.financial_retained_until, i18n.language)
                : ""}
          </Cell>
        </tr>
      ))}
    </Table>
  );
}

// --- legal holds (T06/T07) ----------------------------------------------------------------------

function HoldsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const holds = useQuery({
    queryKey: ["legal-holds"],
    queryFn: async () => unwrap(await api.GET("/api/v1/legal-holds", { params: { query: PAGE } })),
  });
  const [person, setPerson] = useState<PersonRef | null>(null);
  const [reason, setReason] = useState("");
  const place = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/legal-holds", {
          body: {
            subject_type: person?.subject_type ?? "",
            subject_id: person?.subject_id ?? "",
            reason,
          },
        }),
      ),
    onSuccess: () => {
      setPerson(null);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["legal-holds"] });
    },
  });
  const release = useMutation({
    mutationFn: async ({ id, why }: { id: string; why: string }) =>
      unwrap(
        await api.POST("/api/v1/legal-holds/{id}/release", {
          params: { path: { id } },
          body: { reason: why },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["legal-holds"] }),
  });
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">{t("privacyCentre.holdsHint")}</p>
      {holds.data ? (
        <Table
          caption={t("privacyCentre.tabs.holds")}
          headers={[
            t("privacyCentre.person"),
            t("privacyCentre.reason"),
            t("privacyCentre.placed"),
            t("privacyCentre.status"),
            "",
          ]}
        >
          {holds.data.results.map((h: Hold) => (
            <tr key={h.id}>
              <Cell>{h.subject_label || h.subject_id}</Cell>
              <Cell>{h.reason}</Cell>
              <Cell>{formatDate(h.placed_at, i18n.language)}</Cell>
              <Cell>
                {h.active
                  ? t("privacyCentre.holdActive")
                  : t("privacyCentre.holdReleased", { reason: h.release_reason })}
              </Cell>
              <Cell>
                {h.active ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      const why = window.prompt(t("privacyCentre.releaseReason")) ?? "";
                      if (why) release.mutate({ id: h.id, why });
                    }}
                  >
                    {t("privacyCentre.release")}
                  </Button>
                ) : null}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : (
        <Spinner label={t("grid.loading")} />
      )}
      <FormCard
        title={t("privacyCentre.placeHold")}
        submit={t("privacyCentre.placeHoldSubmit")}
        pending={place.isPending}
        error={place.error}
        onSubmit={() => place.mutate()}
      >
        <PersonPicker value={person} onChange={setPerson} />
        <TextArea label={t("privacyCentre.reason")} required value={reason} onChange={setReason} />
      </FormCard>
    </div>
  );
}

// --- retention (T07) ----------------------------------------------------------------------------

function RetentionSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const policies = useQuery({
    queryKey: ["retention-policies"],
    queryFn: async () => unwrap(await api.GET("/api/v1/retention-policies")),
  });
  const runs = useQuery({
    queryKey: ["retention-runs"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/retention-runs", { params: { query: { page_size: 20 } } })),
  });
  const update = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: Partial<Policy> }) =>
      unwrap(
        await api.PATCH("/api/v1/retention-policies/{id}", {
          params: { path: { id } },
          body,
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["retention-policies"] }),
  });
  const run = useMutation({
    mutationFn: async (dryRun: boolean) =>
      unwrap(await api.POST("/api/v1/retention-runs", { body: { dry_run: dryRun } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["retention-runs"] }),
  });
  return (
    <div className="space-y-6">
      {policies.data ? (
        <Table
          caption={t("privacyCentre.retentionPolicies")}
          headers={[t("privacyCentre.category"), t("privacyCentre.keepFor"), t("privacyCentre.on")]}
        >
          {policies.data.map((p) => (
            <tr key={p.id}>
              <Cell>{p.category_label}</Cell>
              <Cell>
                <input
                  aria-label={t("privacyCentre.daysFor", { category: p.category_label })}
                  className="w-28 rounded-md border border-border bg-background px-2 py-1"
                  type="number"
                  min={1}
                  defaultValue={String(p.period_days)}
                  onBlur={(e) => {
                    const days = Number(e.target.value);
                    if (days && days !== p.period_days)
                      update.mutate({ id: p.id, body: { period_days: days } });
                  }}
                />{" "}
                {t("privacyCentre.days")}
              </Cell>
              <Cell>
                <input
                  type="checkbox"
                  aria-label={t("privacyCentre.enabledFor", { category: p.category_label })}
                  checked={p.enabled}
                  onChange={(e) => update.mutate({ id: p.id, body: { enabled: e.target.checked } })}
                />
              </Cell>
            </tr>
          ))}
        </Table>
      ) : (
        <Spinner label={t("grid.loading")} />
      )}
      {update.error ? <Alert tone="danger">{update.error.message}</Alert> : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => run.mutate(true)} disabled={run.isPending}>
          {t("privacyCentre.dryRun")}
        </Button>
        <Button
          variant="danger"
          onClick={() => {
            if (window.confirm(t("privacyCentre.purgeConfirm"))) run.mutate(false);
          }}
          disabled={run.isPending}
        >
          {t("privacyCentre.purgeNow")}
        </Button>
      </div>
      {run.isSuccess ? <p role="status">{t("privacyCentre.runStarted")}</p> : null}
      {runs.data ? (
        <Table
          caption={t("privacyCentre.runs")}
          headers={[
            t("privacyCentre.started"),
            t("privacyCentre.mode"),
            t("privacyCentre.status"),
            t("privacyCentre.report"),
          ]}
        >
          {runs.data.results.map((r: Run) => (
            <tr key={r.id}>
              <Cell>{formatDateTime(r.started_at, i18n.language)}</Cell>
              <Cell>
                {r.dry_run ? t("privacyCentre.dryRunMode") : t("privacyCentre.purgeMode")}
              </Cell>
              <Cell>{t(`privacyCentre.runStatuses.${r.status}`)}</Cell>
              <Cell>
                {Object.entries(r.report as Record<string, { due?: number; done?: number }>)
                  .map(([k, v]) => `${k}: ${r.dry_run ? (v.due ?? 0) : (v.done ?? 0)}`)
                  .join(", ")}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : null}
    </div>
  );
}

// --- agreement and sub-processors (T11) ---------------------------------------------------------

function AgreementSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const dpa = useQuery({
    queryKey: ["dpa"],
    queryFn: async () => unwrap(await api.GET("/api/v1/dpa")),
  });
  const subprocessors = useQuery({
    queryKey: ["subprocessors"],
    queryFn: async () => unwrap(await api.GET("/api/v1/subprocessors")),
  });
  const [form, setForm] = useState({ signer_name: "", signer_title: "", company_name: "" });
  const accept = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/dpa", {
          body: { ...form, version: dpa.data?.version ?? "" },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["dpa"], data),
  });
  const errors = fieldErrors(accept.error);
  if (!dpa.data) return <Spinner label={t("grid.loading")} />;
  const d = dpa.data;
  return (
    <div className="space-y-6">
      <section aria-labelledby="dpa" className="space-y-2">
        <h2 id="dpa" className="font-semibold">
          {t("privacyCentre.dpaTitle", { version: d.version })}
        </h2>
        <p className="text-sm">
          <a href={d.url} className={link} target="_blank" rel="noreferrer">
            {t("privacyCentre.readDpa")}
          </a>
        </p>
        {d.accepted && d.acceptance ? (
          <Alert tone="success">
            {t("privacyCentre.dpaAccepted", {
              name: d.acceptance.signer_name,
              company: d.acceptance.company_name,
              date: formatDate(d.acceptance.accepted_at, i18n.language),
            })}
          </Alert>
        ) : (
          <FormCard
            title={t("privacyCentre.acceptDpa")}
            submit={t("privacyCentre.acceptDpaSubmit")}
            pending={accept.isPending}
            error={accept.error}
            onSubmit={() => accept.mutate()}
          >
            <TextField
              label={t("privacyCentre.signerName")}
              required
              value={form.signer_name}
              error={errors.signer_name}
              onChange={(e) => setForm({ ...form, signer_name: e.target.value })}
            />
            <TextField
              label={t("privacyCentre.signerTitle")}
              value={form.signer_title}
              onChange={(e) => setForm({ ...form, signer_title: e.target.value })}
            />
            <TextField
              label={t("privacyCentre.companyName")}
              required
              value={form.company_name}
              onChange={(e) => setForm({ ...form, company_name: e.target.value })}
            />
          </FormCard>
        )}
      </section>
      {subprocessors.data ? (
        <Table
          caption={t("privacyCentre.subprocessors", { version: subprocessors.data.version })}
          headers={[
            t("privacyCentre.subprocessor"),
            t("privacyCentre.purpose"),
            t("privacyCentre.data"),
            t("privacyCentre.location"),
          ]}
        >
          {subprocessors.data.subprocessors.map((s) => (
            <tr key={s.name}>
              <Cell>
                {s.name}
                {s.optional ? ` (${t("privacyCentre.optionalIntegration")})` : ""}
              </Cell>
              <Cell>{s.purpose}</Cell>
              <Cell>{s.data_categories}</Cell>
              <Cell>{s.location}</Cell>
            </tr>
          ))}
        </Table>
      ) : null}
    </div>
  );
}
