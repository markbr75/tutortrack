import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  Disclosure,
  FactList,
  figureCell,
  PageHeader,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
  Tabs,
  TextField,
  UnitField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { useIsPhone } from "../billing/useIsPhone";
import { RecordHeader } from "../components/RecordHeader";
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

const link = "font-medium text-link underline-offset-2 hover:underline";

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
    <section className="max-w-5xl">
      <PageHeader
        title={t("privacyCentre.title")}
        description={t("designS9b.privacy.description")}
      />
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
  // Overdue is margin red (the One Red Rule); a deadline still to come is a faded caption.
  return (
    <span className={days < 0 ? "font-semibold text-margin" : "text-muted-foreground"}>
      {days < 0
        ? t("privacyCentre.overdueBy", { count: -days })
        : t("privacyCentre.dueIn", { count: days })}
    </span>
  );
}

function RequestsSection() {
  const { t, i18n } = useTranslation();
  const phone = useIsPhone();
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
  const rows = requests.data?.results ?? [];
  return (
    <div className="space-y-6">
      <Table
        caption={t("privacyCentre.requests")}
        loading={requests.isPending}
        empty={requests.data && !rows.length ? t("designS9b.privacy.noRequests") : undefined}
        aside={
          <SelectField
            label={t("privacyCentre.show")}
            hideLabel
            size="sm"
            value={open}
            onChange={(e) => setOpen(e.target.value)}
            options={[
              { value: "true", label: t("privacyCentre.openRequests") },
              { value: "false", label: t("privacyCentre.closedRequests") },
              { value: "", label: t("privacyCentre.allRequests") },
            ]}
          />
        }
        columns={[
          { key: "ref", header: t("privacyCentre.reference") },
          ...(phone
            ? []
            : [
                { key: "kind", header: t("privacyCentre.kind") },
                { key: "person", header: t("privacyCentre.person") },
              ]),
          { key: "status", header: t("privacyCentre.status") },
          ...(phone ? [] : [{ key: "received", header: t("privacyCentre.received") }]),
          { key: "deadline", header: t("privacyCentre.deadline") },
        ]}
      >
        {rows.map((r) => (
          <tr key={r.id}>
            <Cell className="min-w-32">
              <Link to="/privacy/requests/$requestId" params={{ requestId: r.id }} className={link}>
                {r.reference}
              </Link>
              {phone ? (
                <span className="block text-xs text-muted-foreground">
                  {[t(`privacyCentre.kinds.${r.kind}`), r.subject_label || r.requester_name]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              ) : null}
            </Cell>
            {phone ? null : (
              <>
                <Cell className="min-w-40">{t(`privacyCentre.kinds.${r.kind}`)}</Cell>
                <Cell className="min-w-32">{r.subject_label || r.requester_name}</Cell>
              </>
            )}
            <Cell>{t(`privacyCentre.statuses.${r.status}`)}</Cell>
            {phone ? null : (
              <Cell className="whitespace-nowrap tabular-nums">
                {formatDate(r.received_at, i18n.language)}
              </Cell>
            )}
            <Cell className="whitespace-nowrap tabular-nums">
              {formatDate(r.due_at, i18n.language)}
              <span className="block text-xs">
                <DueBadge request={r} />
              </span>
            </Cell>
          </tr>
        ))}
      </Table>
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
    <article className="max-w-3xl">
      <RecordHeader
        back={<Link to="/privacy">{t("privacyCentre.title")}</Link>}
        title={`${r.reference} · ${t(`privacyCentre.kinds.${r.kind}`)}`}
        description={
          <span className="tabular-nums">
            {t(`privacyCentre.statuses.${r.status}`)} ·{" "}
            {t("privacyCentre.dueOn", { date: formatDate(r.due_at, i18n.language) })}{" "}
            <DueBadge request={r} />
          </span>
        }
      />
      <div className="space-y-6">
        <RuledPanel flush title={t("designS9b.privacy.details")}>
          <FactList
            items={[
              [
                t("privacyCentre.person"),
                r.subject_label
                  ? `${r.subject_label} (${t(`privacyCentre.subjectTypes.${r.subject_type}`)})`
                  : "",
              ],
              [
                t("privacyCentre.requester"),
                `${r.requester_name}${r.requester_email ? ` <${r.requester_email}>` : ""} · ${t(
                  `privacyCentre.relationships.${r.relationship}`,
                )}`,
              ],
              [
                t("privacyCentre.received"),
                <span key="received" className="tabular-nums">
                  {formatDateTime(r.received_at, i18n.language)} ·{" "}
                  {t(`privacyCentre.channels.${r.channel}`)}
                </span>,
              ],
              [
                t("privacyCentre.details"),
                r.details ? <span className="whitespace-pre-wrap">{r.details}</span> : "",
              ],
            ]}
          />
        </RuledPanel>

        <RuledPanel
          flush
          titleId="checks"
          title={t("privacyCentre.verification")}
          aside={
            r.verified_at ? (
              <span role="status" className="text-muted-foreground tabular-nums">
                {t("privacyCentre.verifiedOn", {
                  date: formatDateTime(r.verified_at, i18n.language),
                })}
              </span>
            ) : null
          }
        >
          <ul className="divide-y divide-rule">
            {r.checklist.map((c) => (
              <li key={c.key} className="px-5 py-2.5">
                <CheckboxField
                  checked={c.done}
                  disabled={!!r.closed_at || verify.isPending}
                  onChange={(e) => verify.mutate({ [c.key]: e.target.checked })}
                  label={
                    <>
                      {c.title}
                      {c.is_required ? null : (
                        <span className="text-muted-foreground">
                          {" "}
                          ({t("privacyCentre.optional")})
                        </span>
                      )}
                    </>
                  }
                />
              </li>
            ))}
          </ul>
          {verify.error ? (
            <div className="px-5 pb-4">
              <Alert tone="danger">{verify.error.message}</Alert>
            </div>
          ) : null}
        </RuledPanel>

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
          <RuledPanel
            flush
            titleId="manage"
            title={t("privacyCentre.manage")}
            footer={
              <>
                <Button variant="secondary" onClick={() => extend.mutate()} disabled={!reason}>
                  {t("privacyCentre.extend")}
                </Button>
                <Button
                  variant="ghost"
                  className="text-muted-foreground"
                  onClick={() => reject.mutate()}
                  disabled={!reason}
                >
                  {t("privacyCentre.reject")}
                </Button>
              </>
            }
          >
            <div className="space-y-3 px-5 py-4">
              <TextArea
                label={t("privacyCentre.reason")}
                value={reason}
                onChange={setReason}
                rows={2}
              />
              <UnitField
                label={t("privacyCentre.extendDays")}
                unit={t("privacyCentre.days")}
                min={1}
                max={60}
                value={String(extendDays)}
                onChange={(e) => setExtendDays(Number(e.target.value))}
              />
              {extend.error || reject.error ? (
                <Alert tone="danger" className="sm:col-span-full">
                  {(extend.error ?? reject.error)?.message}
                </Alert>
              ) : null}
            </div>
          </RuledPanel>
        ) : (
          <p className="text-sm text-muted-foreground tabular-nums">
            {t("privacyCentre.closedOn", {
              date: formatDateTime(r.closed_at, i18n.language),
            })}
            {r.close_reason ? ` · ${r.close_reason}` : ""}
          </p>
        )}
      </div>
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
    <RuledPanel
      flush
      titleId="review"
      title={t("privacyCentre.reviewExport")}
      description={t("privacyCentre.reviewExportHint")}
      footer={
        <Button onClick={() => approve.mutate()} loading={approve.isPending}>
          {t("privacyCentre.approveExport", { count: redactions.length })}
        </Button>
      }
    >
      <ul className="divide-y divide-rule">
        {preview.data.sections.map((section) => (
          <li key={section.key} className="px-5 py-3.5">
            <Disclosure summary={`${section.title} (${section.records.length})`}>
              <ul className="mt-3 divide-y divide-rule rounded-md border border-border">
                {section.records.map((record) => {
                  const id = String(record.id ?? "");
                  const ref = { section: section.key, record_id: id };
                  return (
                    <li key={id} className="space-y-1.5 px-3 py-2.5">
                      <CheckboxField
                        label={t("privacyCentre.redactRecord")}
                        checked={has(ref)}
                        onChange={() => toggle(ref)}
                      />
                      <pre className="font-sans text-xs break-words whitespace-pre-wrap text-muted-foreground">
                        {JSON.stringify(record, null, 1)}
                      </pre>
                    </li>
                  );
                })}
              </ul>
            </Disclosure>
          </li>
        ))}
        {preview.data.files.length ? (
          <li className="px-5 py-3.5">
            <fieldset className="space-y-2">
              <legend className="mb-2 text-sm font-medium">{t("privacyCentre.files")}</legend>
              {preview.data.files.map((f) => (
                <CheckboxField
                  key={f.id}
                  label={t("privacyCentre.redactFile", { name: f.filename })}
                  checked={has({ file_id: f.id })}
                  onChange={() => toggle({ file_id: f.id })}
                />
              ))}
            </fieldset>
          </li>
        ) : null}
      </ul>
      {approve.error ? (
        <div className="px-5 pb-4">
          <Alert tone="danger">{approve.error.message}</Alert>
        </div>
      ) : null}
    </RuledPanel>
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
    <RuledPanel
      flush
      titleId="erasure"
      title={t("privacyCentre.erasure")}
      footer={
        request.status === "in_review" ? (
          <Button variant="danger" onClick={() => approve.mutate()} loading={approve.isPending}>
            {t("privacyCentre.approveErasure")}
          </Button>
        ) : undefined
      }
    >
      {preview || approve.error ? (
        <div className="space-y-3 px-5 py-4 text-sm">
          {preview ? (
            <>
              <p>
                {t("privacyCentre.erasureCovers", {
                  list: Object.entries(preview.subjects)
                    .map(([k, n]) => `${n} × ${t(`privacyCentre.subjectTypes.${k}`)}`)
                    .join(", "),
                })}
              </p>
              <p className="text-muted-foreground">
                {t("privacyCentre.financialKept", { years: preview.financial_retention_years })}
              </p>
              {preview.holds.length ? (
                <Alert tone="warning">{t("privacyCentre.heldWarning")}</Alert>
              ) : null}
            </>
          ) : null}
          {approve.error ? <Alert tone="danger">{approve.error.message}</Alert> : null}
        </div>
      ) : null}
      {record.data ? <ErasureReport record={record.data} locale={i18n.language} /> : null}
    </RuledPanel>
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
  const caption = t("privacyCentre.erasureReport", {
    status: t(`privacyCentre.erasureStatuses.${record.status}`),
    date: record.completed_at ? formatDateTime(record.completed_at, locale) : "",
  });
  return (
    <div className="border-t border-border">
      <p className="px-5 pt-3.5 text-sm font-semibold tabular-nums">{caption}</p>
      <RuledTable
        caption={caption}
        columns={[
          { key: "area", header: t("privacyCentre.area") },
          { key: "anon", header: t("privacyCentre.anonymised"), end: true, width: "w-28" },
          { key: "deleted", header: t("privacyCentre.deleted"), end: true, width: "w-24" },
          { key: "kept", header: t("privacyCentre.retained") },
        ]}
      >
        {Object.entries(report)
          .filter(([, v]) => v && typeof v === "object" && "anonymised" in v)
          .map(([key, v]) => (
            <tr key={key}>
              <td>{key}</td>
              <td className={figureCell}>{v.anonymised}</td>
              <td className={figureCell}>{v.deleted}</td>
              <td>
                <span className="tabular-nums">{v.retained}</span>
                {v.notes?.length ? (
                  <span className="block text-xs text-muted-foreground">{v.notes.join("; ")}</span>
                ) : null}
              </td>
            </tr>
          ))}
      </RuledTable>
    </div>
  );
}

function ErasuresSection() {
  const { t, i18n } = useTranslation();
  const erasures = useQuery({
    queryKey: ["erasures"],
    queryFn: async () => unwrap(await api.GET("/api/v1/erasures", { params: { query: PAGE } })),
  });
  const rows = erasures.data?.results ?? [];
  return (
    <Table
      caption={t("privacyCentre.tabs.erasures")}
      loading={erasures.isPending}
      empty={erasures.data && !rows.length ? t("designS9b.privacy.noErasures") : undefined}
      columns={[
        { key: "person", header: t("privacyCentre.person") },
        { key: "why", header: t("privacyCentre.reasonCol") },
        { key: "status", header: t("privacyCentre.status") },
        { key: "done", header: t("privacyCentre.completed") },
        { key: "until", header: t("privacyCentre.financialUntil") },
      ]}
    >
      {rows.map((e) => (
        <tr key={e.id}>
          <Cell className="min-w-32 font-medium">
            {(e.labels as Record<string, string>)[`${e.subject_type}:${e.subject_id}`]}
          </Cell>
          <Cell>{t(`privacyCentre.erasureReasons.${e.reason}`)}</Cell>
          <Cell>{t(`privacyCentre.erasureStatuses.${e.status}`)}</Cell>
          <Cell className="whitespace-nowrap tabular-nums">
            {e.completed_at ? formatDateTime(e.completed_at, i18n.language) : ""}
          </Cell>
          <Cell className="whitespace-nowrap tabular-nums">
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
  const [releasing, setReleasing] = useState<string | null>(null);
  const [why, setWhy] = useState("");
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
    onSuccess: () => {
      setReleasing(null);
      void queryClient.invalidateQueries({ queryKey: ["legal-holds"] });
    },
  });
  const rows = holds.data?.results ?? [];
  return (
    <div className="space-y-6">
      <Table
        caption={t("privacyCentre.tabs.holds")}
        description={t("privacyCentre.holdsHint")}
        loading={holds.isPending}
        empty={holds.data && !rows.length ? t("designS9b.privacy.noHolds") : undefined}
        columns={[
          { key: "person", header: t("privacyCentre.person") },
          { key: "reason", header: t("privacyCentre.reason") },
          { key: "placed", header: t("privacyCentre.placed") },
          { key: "status", header: t("privacyCentre.status") },
          { key: "actions", header: t("common.actions", "Actions"), hidden: true },
        ]}
      >
        {rows.map((h: Hold) => (
          <tr key={h.id}>
            <Cell className="min-w-32 font-medium">{h.subject_label || h.subject_id}</Cell>
            <Cell className="min-w-40">{h.reason}</Cell>
            <Cell className="whitespace-nowrap tabular-nums">
              {formatDate(h.placed_at, i18n.language)}
            </Cell>
            <Cell className={h.active ? undefined : "text-muted-foreground"}>
              {h.active
                ? t("privacyCentre.holdActive")
                : t("privacyCentre.holdReleased", { reason: h.release_reason })}
            </Cell>
            <Cell className="py-1.5 text-right align-middle">
              {h.active ? (
                releasing === h.id ? (
                  <form
                    className="flex flex-wrap items-center justify-end gap-2"
                    onKeyDown={(e) => {
                      if (e.key === "Escape") setReleasing(null);
                    }}
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (why.trim()) release.mutate({ id: h.id, why: why.trim() });
                    }}
                  >
                    <TextField
                      label={t("privacyCentre.releaseReason")}
                      hideLabel
                      size="sm"
                      placeholder={t("privacyCentre.releaseReason")}
                      className="min-w-56"
                      autoFocus
                      required
                      value={why}
                      onChange={(e) => setWhy(e.target.value)}
                    />
                    <Button type="submit" size="sm" loading={release.isPending}>
                      {t("privacyCentre.release")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="text-muted-foreground"
                      onClick={() => setReleasing(null)}
                    >
                      {t("common.cancel")}
                    </Button>
                  </form>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    className="whitespace-nowrap"
                    onClick={() => {
                      setWhy("");
                      setReleasing(h.id);
                    }}
                  >
                    {t("privacyCentre.release")}
                  </Button>
                )
              ) : null}
            </Cell>
          </tr>
        ))}
      </Table>
      {release.error ? <Alert tone="danger">{release.error.message}</Alert> : null}
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
  const runRows = runs.data?.results ?? [];
  return (
    <div className="space-y-6">
      <Table
        caption={t("privacyCentre.retentionPolicies")}
        loading={policies.isPending}
        columns={[
          { key: "category", header: t("privacyCentre.category") },
          { key: "keep", header: t("privacyCentre.keepFor"), width: "w-40" },
          { key: "on", header: t("privacyCentre.on"), center: true, width: "w-20" },
        ]}
        footer={
          <>
            <Button variant="secondary" onClick={() => run.mutate(true)} disabled={run.isPending}>
              {t("privacyCentre.dryRun")}
            </Button>
            <Button
              variant="ghost"
              className="text-muted-foreground"
              onClick={() => {
                if (window.confirm(t("privacyCentre.purgeConfirm"))) run.mutate(false);
              }}
              disabled={run.isPending}
            >
              {t("privacyCentre.purgeNow")}
            </Button>
            {run.isSuccess ? (
              <p role="status" className="basis-full text-success">
                {t("privacyCentre.runStarted")}
              </p>
            ) : null}
          </>
        }
      >
        {(policies.data ?? []).map((p) => (
          <tr key={p.id}>
            <Cell className="min-w-40 align-middle">{p.category_label}</Cell>
            <Cell className="py-1.5 align-middle">
              <UnitField
                label={t("privacyCentre.daysFor", { category: p.category_label })}
                hideLabel
                size="sm"
                unit={t("privacyCentre.days")}
                min={1}
                defaultValue={String(p.period_days)}
                onBlur={(e) => {
                  const days = Number(e.target.value);
                  if (days && days !== p.period_days)
                    update.mutate({ id: p.id, body: { period_days: days } });
                }}
              />
            </Cell>
            <Cell className="text-center align-middle">
              <input
                type="checkbox"
                className="size-4"
                aria-label={t("privacyCentre.enabledFor", { category: p.category_label })}
                checked={p.enabled}
                onChange={(e) => update.mutate({ id: p.id, body: { enabled: e.target.checked } })}
              />
            </Cell>
          </tr>
        ))}
      </Table>
      {update.error ? <Alert tone="danger">{update.error.message}</Alert> : null}
      {run.error ? <Alert tone="danger">{run.error.message}</Alert> : null}
      <Table
        caption={t("privacyCentre.runs")}
        loading={runs.isPending}
        empty={runs.data && !runRows.length ? t("designS9b.privacy.noRuns") : undefined}
        columns={[
          { key: "started", header: t("privacyCentre.started") },
          { key: "mode", header: t("privacyCentre.mode") },
          { key: "status", header: t("privacyCentre.status") },
          { key: "report", header: t("privacyCentre.report") },
        ]}
      >
        {runRows.map((r: Run) => (
          <tr key={r.id}>
            <Cell className="whitespace-nowrap tabular-nums">
              {formatDateTime(r.started_at, i18n.language)}
            </Cell>
            <Cell>{r.dry_run ? t("privacyCentre.dryRunMode") : t("privacyCentre.purgeMode")}</Cell>
            <Cell className={r.status === "failed" ? "font-medium text-danger" : undefined}>
              {t(`privacyCentre.runStatuses.${r.status}`)}
            </Cell>
            <Cell className="min-w-48 text-xs text-muted-foreground tabular-nums">
              {Object.entries(r.report as Record<string, { due?: number; done?: number }>)
                .map(([k, v]) => `${k}: ${r.dry_run ? (v.due ?? 0) : (v.done ?? 0)}`)
                .join(", ")}
            </Cell>
          </tr>
        ))}
      </Table>
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
  const subs = subprocessors.data?.subprocessors ?? [];
  return (
    <div className="space-y-6">
      {d.accepted && d.acceptance ? (
        <RuledPanel
          titleId="dpa"
          title={t("privacyCentre.dpaTitle", { version: d.version })}
          aside={<span className="text-success">{t("designS9b.privacy.accepted")}</span>}
          footer={
            <a href={d.url} className={link} target="_blank" rel="noreferrer">
              {t("privacyCentre.readDpa")}
            </a>
          }
        >
          <p className="text-sm tabular-nums">
            {t("privacyCentre.dpaAccepted", {
              name: d.acceptance.signer_name,
              company: d.acceptance.company_name,
              date: formatDate(d.acceptance.accepted_at, i18n.language),
            })}
          </p>
        </RuledPanel>
      ) : (
        <FormCard
          title={t("privacyCentre.dpaTitle", { version: d.version })}
          description={
            <a href={d.url} className={link} target="_blank" rel="noreferrer">
              {t("privacyCentre.readDpa")}
            </a>
          }
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
      <Table
        caption={t("privacyCentre.subprocessors", { version: subprocessors.data?.version ?? "" })}
        loading={subprocessors.isPending}
        columns={[
          { key: "name", header: t("privacyCentre.subprocessor") },
          { key: "purpose", header: t("privacyCentre.purpose") },
          { key: "data", header: t("privacyCentre.data") },
          { key: "where", header: t("privacyCentre.location") },
        ]}
      >
        {subs.map((sp) => (
          <tr key={sp.name}>
            <Cell className="min-w-36">
              <span className="font-medium">{sp.name}</span>
              {sp.optional ? (
                <span className="block text-xs text-muted-foreground">
                  {t("privacyCentre.optionalIntegration")}
                </span>
              ) : null}
            </Cell>
            <Cell className="min-w-48">{sp.purpose}</Cell>
            <Cell className="min-w-40">{sp.data_categories}</Cell>
            <Cell>{sp.location}</Cell>
          </tr>
        ))}
      </Table>
    </div>
  );
}
