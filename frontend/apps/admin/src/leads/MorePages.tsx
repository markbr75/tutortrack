import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FigureStrip,
  NamePlate,
  Panel,
  PanelRow,
  PanelRows,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api } from "../api";
import { Turnstile } from "../components/Turnstile";
import { PublicFileField, type UploadTarget } from "../components/PublicFileField";
import { PublicLayout } from "../layout/PublicLayout";
import { LeadsPage } from "./LeadsPages";
import { WaitlistSuggestions } from "./WaitlistSuggestions";

type FormDef = components["schemas"]["Form"];

export interface Field {
  key: string;
  label: string;
  type: string;
  required?: boolean;
  options?: string[];
  maps_to?: string;
  show_if?: { field: string; equals: unknown };
  /** G6: the E29 consent type a ticked ``consent`` field records. */
  consent_key?: string;
  /** G5a: what a ``file`` field takes (``document``, ``cv`` or ``video``), and how many. */
  file_kind?: "document" | "cv" | "video";
  multiple?: boolean;
}

export interface Schema {
  steps: { title: string; fields: Field[] }[];
}

const STARTER: Schema = {
  steps: [
    {
      title: "About you",
      fields: [
        { key: "first_name", label: "First name", type: "text", required: true, maps_to: "contact.first_name" },
        { key: "last_name", label: "Last name", type: "text", maps_to: "contact.last_name" },
        { key: "email", label: "Email", type: "email", required: true, maps_to: "contact.email" },
        { key: "phone", label: "Phone", type: "phone", maps_to: "contact.phone" },
      ],
    },
    {
      title: "Your children",
      fields: [
        { key: "students", label: "Students", type: "students", required: true, maps_to: "students" },
        { key: "notes", label: "Anything else?", type: "textarea", maps_to: "enquiry.notes" },
      ],
    },
  ],
}; // prettier-ignore

const FIELD_TYPES = ["text", "textarea", "email", "phone", "number", "date", "select",
                     "checkbox", "consent", "postcode", "students", "file"]; // prettier-ignore
// G5a: tutor application forms (E18) map onto the applicant and take referees.
const APPLICATION_FIELD_TYPES = [...FIELD_TYPES, "referees"];
const APPLICATION_MAPPINGS = ["", "applicant.first_name", "applicant.last_name",
  "applicant.email", "applicant.phone", "applicant.postcode", "applicant.subjects",
  "applicant.qualifications", "applicant.experience", "applicant.right_to_work",
  "applicant.video_url", "applicant.cv", "applicant.video", "referees"]; // prettier-ignore
const FILE_KINDS = ["document", "cv", "video"] as const;
const CONSENT_KEYS = ["", "terms", "privacy-policy", "marketing-email", "marketing-sms",
                      "photo-video", "lesson-recording"]; // prettier-ignore
const MAPPINGS = ["", "contact.first_name", "contact.last_name", "contact.email", "contact.phone",
                  "client.postcode", "students", "enquiry.notes", "enquiry.subjects",
                  "enquiry.how_heard"]; // prettier-ignore

/** Enquiry and registration forms (FR-17-1, FR-17-7). */
export function FormsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<FormDef | null>(null);
  const forms = useQuery({
    queryKey: ["forms"],
    queryFn: async () => unwrap(await api.GET("/api/v1/forms")),
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/forms", {
          body: {
            name: t("leads.newFormName"),
            slug: `enquiry-${Date.now().toString(36)}`,
            type: "enquiry",
            schema: STARTER as unknown as Record<string, never>,
            settings: {},
            published: false,
          },
        }),
      ),
    onSuccess: (form) => {
      setEditing(form);
      void queryClient.invalidateQueries({ queryKey: ["forms"] });
    },
  });
  return (
    <LeadsPage
      title={t("leads.forms")}
      actions={
        <Button onClick={() => create.mutate()} loading={create.isPending}>
          {t("leads.newForm")}
        </Button>
      }
    >
      {create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
      <div className="rounded-xl border border-border bg-surface">
        {forms.isPending ? (
          <div className="px-5 py-4">
            <Spinner label={t("grid.loading")} />
          </div>
        ) : forms.data?.length ? (
          <PanelRows>
            {forms.data.map((f) => (
              <PanelRow key={f.id}>
                <NamePlate
                  name={f.name}
                  context={`${t(`leads.formTypes.${f.type ?? "enquiry"}`)} · ${
                    f.published ? t("leads.published") : t("leads.draft")
                  }`}
                  aside={
                    <>
                      {f.published ? (
                        <a
                          className="font-medium text-link underline-offset-2 hover:underline"
                          href={`/f/${f.slug}`}
                        >
                          {t("leads.openForm")}
                        </a>
                      ) : null}
                      <Button size="sm" variant="secondary" onClick={() => setEditing(f)}>
                        {t("leads.edit")}
                      </Button>
                    </>
                  }
                />
              </PanelRow>
            ))}
          </PanelRows>
        ) : (
          <p className="px-5 py-10 text-center text-sm text-muted-foreground">
            {t("designS5.leads.noForms")}
          </p>
        )}
      </div>
      {editing ? <FormEditor form={editing} onClose={() => setEditing(null)} /> : null}
    </LeadsPage>
  );
}

function FormEditor({ form, onClose }: { form: FormDef; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState(form.name);
  const [slug, setSlug] = useState(form.slug);
  const [schema, setSchema] = useState<Schema>(form.schema as unknown as Schema);
  const [published, setPublished] = useState(Boolean(form.published));
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/forms/{id}", {
          params: { path: { id: form.id } },
          body: { name, slug, published, schema: schema as unknown as Record<string, never> },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["forms"] });
      onClose();
    },
  });
  const update = (step: number, index: number, patch: Partial<Field>) =>
    setSchema({
      steps: schema.steps.map((s, i) =>
        i !== step
          ? s
          : { ...s, fields: s.fields.map((f, j) => (j === index ? { ...f, ...patch } : f)) },
      ),
    });
  const add = (step: number) =>
    setSchema({
      steps: schema.steps.map((s, i) =>
        i !== step
          ? s
          : {
              ...s,
              fields: [
                ...s.fields,
                { key: `field_${s.fields.length + 1}`, label: "", type: "text" },
              ],
            },
      ),
    });
  const isApplication = form.type === "application";
  const fieldTypes = isApplication ? APPLICATION_FIELD_TYPES : FIELD_TYPES;
  const mappings = isApplication ? APPLICATION_MAPPINGS : MAPPINGS;
  const remove = (step: number, index: number) =>
    setSchema({
      steps: schema.steps.map((s, i) =>
        i !== step ? s : { ...s, fields: s.fields.filter((_, j) => j !== index) },
      ),
    });
  return (
    <section
      aria-label={t("leads.editForm")}
      className="rounded-xl border border-border bg-surface"
    >
      <h2 className="border-b border-border px-5 py-3.5 text-base font-semibold">
        {t("leads.editForm")}
      </h2>
      <div className="space-y-4 px-5 py-4">
      <div className="flex flex-wrap items-end gap-3">
        <TextField
          label={t("leads.formName")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <TextField
          label={t("leads.formSlug")}
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
        />
        <label className="flex h-10 items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={published}
            onChange={(e) => setPublished(e.target.checked)}
          />
          {t("leads.publish")}
        </label>
      </div>
      {schema.steps.map((step, s) => (
        <fieldset key={s} className="rounded-xl border border-border">
          <legend className="float-left w-full border-b border-border px-4 py-2.5 text-sm font-semibold">
            {step.title}
          </legend>
          <div className="clear-both divide-y divide-rule">
          {step.fields.map((f, i) => (
            <div key={i} className="flex flex-wrap items-end gap-2 px-4 py-3 text-sm">
              <TextField
                label={t("leads.fieldLabel")}
                value={f.label}
                onChange={(e) => update(s, i, { label: e.target.value })}
              />
              <TextField
                label={t("leads.fieldKey")}
                value={f.key}
                onChange={(e) => update(s, i, { key: e.target.value })}
              />
              <label className="flex flex-col gap-1">
                <span className="font-medium">{t("leads.fieldType")}</span>
                <select
                  className="h-10 rounded-md border border-field bg-surface px-3 text-sm"
                  value={f.type}
                  onChange={(e) => update(s, i, { type: e.target.value })}
                >
                  {fieldTypes.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="font-medium">{t("leads.fieldMapsTo")}</span>
                <select
                  className="h-10 rounded-md border border-field bg-surface px-3 text-sm"
                  value={f.maps_to ?? ""}
                  onChange={(e) => update(s, i, { maps_to: e.target.value || undefined })}
                >
                  {mappings.map((m) => (
                    <option key={m} value={m}>
                      {m || t("leads.notMapped")}
                    </option>
                  ))}
                </select>
              </label>
              {f.type === "file" ? (
                <>
                  <label className="flex flex-col gap-1">
                    <span className="font-medium">{t("hiring.formBuilder.fileKind")}</span>
                    <select
                      className="h-10 rounded-md border border-field bg-surface px-3 text-sm"
                      value={f.file_kind ?? "document"}
                      onChange={(e) =>
                        update(s, i, { file_kind: e.target.value as Field["file_kind"] })
                      }
                    >
                      {FILE_KINDS.map((k) => (
                        <option key={k} value={k}>
                          {t(`hiring.formBuilder.fileKinds.${k}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex h-10 items-center gap-2">
                    <input
                      type="checkbox"
                      className="size-4"
                      checked={Boolean(f.multiple)}
                      onChange={(e) => update(s, i, { multiple: e.target.checked })}
                    />
                    {t("hiring.formBuilder.multiple")}
                  </label>
                </>
              ) : null}
              {f.type === "consent" ? (
                <label className="flex flex-col gap-1">
                  <span className="font-medium">{t("gapG6.consentKey")}</span>
                  <select
                    className="h-10 rounded-md border border-field bg-surface px-3 text-sm"
                    value={f.consent_key ?? ""}
                    onChange={(e) => update(s, i, { consent_key: e.target.value || undefined })}
                  >
                    {CONSENT_KEYS.map((k) => (
                      <option key={k} value={k}>
                        {t(`gapG6.consentKeys.${k || "default"}`)}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="flex h-10 items-center gap-2">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={Boolean(f.required)}
                  onChange={(e) => update(s, i, { required: e.target.checked })}
                />
                {t("leads.required")}
              </label>
              <Button size="sm" variant="ghost" className="mb-1" onClick={() => remove(s, i)}>
                {t("leads.removeField")}
              </Button>
            </div>
          ))}
          <div className="px-4 py-3">
          <Button size="sm" variant="secondary" onClick={() => add(s)}>
            {t("leads.addField")}
          </Button>
          </div>
          </div>
        </fieldset>
      ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-rule px-5 py-3">
        <Button onClick={() => save.mutate()} loading={save.isPending}>
          {t("common.save")}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          {t("common.cancel")}
        </Button>
      </div>
      {save.error ? (
        <div className="px-5 pb-4">
          <Alert tone="danger">{save.error.message}</Alert>
        </div>
      ) : null}
    </section>
  );
}

/** Waiting students and place offers (FR-17-6). */
export function WaitlistPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [details, setDetails] = useState<Record<string, string>>({});
  const entries = useQuery({
    queryKey: ["waitlist"],
    queryFn: async () => unwrap(await api.GET("/api/v1/waitlist")),
  });
  const offer = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/waitlist/{id}/offer", {
          params: { path: { id } },
          body: { details: details[id] ?? "" },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["waitlist"] }),
  });
  return (
    <LeadsPage title={t("leads.waitlist")}>
      <WaitlistSuggestions />
      <Panel
        title={t("designS5.leads.waiting")}
        flush
        aside={
          entries.data?.results.length ? (
            <span className="text-muted-foreground tabular-nums">
              {entries.data.results.length}
            </span>
          ) : null
        }
      >
        {entries.isPending ? (
          <div className="px-5 py-4">
            <Spinner label={t("grid.loading")} />
          </div>
        ) : null}
        {entries.data && !entries.data.results.length ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">{t("leads.nobodyWaiting")}</p>
        ) : null}
        <PanelRows>
          {entries.data?.results.map((entry) => (
            <PanelRow key={entry.id} className="flex flex-wrap items-end gap-x-4 gap-y-2">
              <span className="w-8 shrink-0 self-center font-semibold tabular-nums">
                #{entry.position}
              </span>
              <NamePlate
                className="min-w-48 flex-1 self-center"
                name={entry.student_name}
                context={[
                  entry.subject || "–",
                  t("leads.since", { date: formatDate(entry.created_at) }),
                ].join(" · ")}
              />
              <TextField
                label={t("leads.offerDetails")}
                size="sm"
                value={details[entry.id] ?? ""}
                onChange={(e) => setDetails({ ...details, [entry.id]: e.target.value })}
              />
              <Button
                size="sm"
                className="h-9"
                disabled={!details[entry.id]}
                onClick={() => offer.mutate(entry.id)}
              >
                {t("leads.offerPlace")}
              </Button>
            </PanelRow>
          ))}
        </PanelRows>
      </Panel>
      {offer.error ? <Alert tone="danger">{offer.error.message}</Alert> : null}
    </LeadsPage>
  );
}

/** Funnel by stage, source and owner (FR-17-8). */
export function FunnelPage() {
  const { t } = useTranslation();
  const report = useQuery({
    queryKey: ["funnel"],
    queryFn: async () => unwrap(await api.GET("/api/v1/leads/reports/funnel")),
  });
  if (!report.data) return <Spinner label={t("grid.loading")} />;
  const r = report.data;
  return (
    <LeadsPage title={t("leads.reports")}>
      <FigureStrip
        label={t("leads.reports")}
        figures={[
          { label: t("leads.enquiries"), value: String(r.total) },
          { label: t("leads.winRate"), value: `${r.win_rate}%` },
          {
            label: t("leads.firstResponse"),
            value:
              r.first_response_hours === null
                ? "–"
                : t("leads.hours", { count: r.first_response_hours }),
          },
        ]}
      />
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-2">
        <RuledTable caption={t("leads.byStage")}>
          <thead className="border-b border-border">
            <tr className="text-left">
              <th scope="col">{t("leads.stage")}</th>
              <th scope="col" className="text-right">
                {t("leads.reached")}
              </th>
              <th scope="col" className="text-right">
                %
              </th>
            </tr>
          </thead>
          <tbody>
            {r.stages.map((s) => (
              <tr key={s.stage}>
                <td>{s.stage}</td>
                <td className="text-right tabular-nums">{s.reached}</td>
                <td className="text-right tabular-nums">{s.rate}</td>
              </tr>
            ))}
          </tbody>
        </RuledTable>
        <RuledTable caption={t("leads.bySource")}>
          <thead className="border-b border-border">
            <tr className="text-left">
              <th scope="col">{t("leads.source")}</th>
              <th scope="col" className="text-right">
                {t("leads.enquiries")}
              </th>
              <th scope="col" className="text-right">
                {t("leads.won")}
              </th>
            </tr>
          </thead>
          <tbody>
            {r.by_source.map((row) => (
              <tr key={row.key}>
                <td>{t(`leads.sources.${row.key}`, { defaultValue: row.key })}</td>
                <td className="text-right tabular-nums">{row.total}</td>
                <td className="text-right tabular-nums">{row.won}</td>
              </tr>
            ))}
            {r.by_source.length === 0 ? (
              <tr>
                <td colSpan={3} className="text-muted-foreground">
                  {t("designS5.leads.noSources")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </RuledTable>
      </div>
    </LeadsPage>
  );
}

/** A hand-built table in a ruled panel, its caption as the panel's heading. */
function RuledTable({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <div
      role="region"
      aria-label={caption}
      tabIndex={0}
      className="overflow-x-auto rounded-xl border border-border bg-surface"
    >
      <table className="w-full text-sm [&_td]:px-5 [&_td]:py-2.5 [&_th]:px-5 [&_th]:py-2.5">
        <caption className="border-b border-border px-5 py-3.5 text-left text-base font-semibold">
          {caption}
        </caption>
        {children}
      </table>
    </div>
  );
}

// --- public pages ---------------------------------------------------------------------------

/** The hosted enquiry or registration form at ``/f/<slug>`` (FR-17-1). */
export function PublicFormPage({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [token, setToken] = useState("");
  const [honeypot, setHoneypot] = useState("");
  const form = useQuery({
    queryKey: ["public-form", slug],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/forms/{slug}", { params: { path: { slug } } })),
    retry: false,
  });
  const submit = useMutation({
    mutationFn: async () => {
      const params = new URLSearchParams(window.location.search);
      const utm = Object.fromEntries(
        [...params.entries()].filter(
          ([k]) => k.startsWith("utm_") || k === "gclid" || k === "fbclid",
        ),
      );
      return unwrap(
        await api.POST("/api/v1/public/forms/{slug}", {
          params: { path: { slug } },
          body: {
            data: answers as Record<string, never>,
            utm: { ...utm, referrer: document.referrer, landing_page: window.location.href },
            captcha_token: token,
            website: honeypot,
          },
        }),
      );
    },
    onSuccess: (result) => {
      if (result.pay_url) window.location.assign(result.pay_url);
      else if (form.data?.redirect_url) window.location.assign(form.data.redirect_url);
    },
  });
  if (form.isError) return <PublicLayout title={t("leads.formMissing")}>{null}</PublicLayout>;
  if (!form.data) return <Spinner label={t("grid.loading")} />;
  const schema = form.data.schema as unknown as Schema;
  const errors = (submit.error as { problem?: { errors?: Record<string, string[]> } } | null)
    ?.problem?.errors;
  const set = (key: string, value: unknown) => setAnswers({ ...answers, [key]: value });
  return (
    <PublicLayout title={form.data.name}>
      {submit.isSuccess ? (
        <p role="status">{form.data.thank_you || t("leads.thanks")}</p>
      ) : (
        <form
          className="space-y-6"
          onSubmit={(e) => {
            e.preventDefault();
            submit.mutate();
          }}
        >
          {schema.steps.map((step, s) => (
            <fieldset key={s} className="space-y-3">
              <legend className="mb-1 text-base font-semibold">{step.title}</legend>
              {step.fields
                .filter((f) => !f.show_if || answers[f.show_if.field] === f.show_if.equals)
                .map((f) => (
                  <PublicField
                    key={f.key}
                    field={f}
                    value={answers[f.key]}
                    error={errors?.[f.key]?.[0]}
                    onChange={(v) => set(f.key, v)}
                    uploadTarget={{ target: "form", slug }}
                  />
                ))}
            </fieldset>
          ))}
          <div aria-hidden="true" className="absolute -left-[9999px]">
            <label>
              Website
              <input
                tabIndex={-1}
                autoComplete="off"
                value={honeypot}
                onChange={(e) => setHoneypot(e.target.value)}
              />
            </label>
          </div>
          {form.data.consent_text ? (
            <p className="text-sm text-muted-foreground">{form.data.consent_text}</p>
          ) : null}
          {form.data.turnstile_site_key ? (
            <Turnstile siteKey={form.data.turnstile_site_key} onToken={setToken} />
          ) : null}
          {submit.error && !errors ? <Alert tone="danger">{submit.error.message}</Alert> : null}
          <Button type="submit" loading={submit.isPending}>
            {t("leads.send")}
          </Button>
        </form>
      )}
    </PublicLayout>
  );
}

export function PublicField({
  field,
  value,
  error,
  onChange,
  uploadTarget,
}: {
  field: Field;
  value: unknown;
  error?: string;
  onChange: (value: unknown) => void;
  /** G5a: where a ``file`` field's uploads go (the form or job opening). */
  uploadTarget?: UploadTarget;
}) {
  const { t } = useTranslation();
  if (field.type === "file") {
    if (!uploadTarget) return null;
    return (
      <PublicFileField
        label={field.label}
        kind={field.file_kind ?? "document"}
        multiple={field.multiple}
        required={field.required}
        error={error}
        where={uploadTarget}
        onChange={onChange}
      />
    );
  }
  if (field.type === "students") {
    const students = (value as { first_name: string; subjects: string }[] | undefined) ?? [
      { first_name: "", subjects: "" },
    ];
    const change = (i: number, patch: Record<string, string>) =>
      onChange(students.map((st, j) => (j === i ? { ...st, ...patch } : st)));
    return (
      <div className="space-y-2">
        <p className="text-sm font-medium">{field.label}</p>
        {students.map((st, i) => (
          <div key={i} className="grid gap-2 sm:grid-cols-2">
            <TextField
              label={t("leads.studentFirstName", { n: i + 1 })}
              required={field.required && i === 0}
              value={st.first_name}
              onChange={(e) => change(i, { first_name: e.target.value })}
            />
            <TextField
              label={t("leads.studentSubjects", { n: i + 1 })}
              value={st.subjects}
              onChange={(e) => change(i, { subjects: e.target.value })}
            />
          </div>
        ))}
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onChange([...students, { first_name: "", subjects: "" }])}
        >
          {t("leads.addStudent")}
        </Button>
        {error ? <p className="text-xs text-danger">{error}</p> : null}
      </div>
    );
  }
  if (field.type === "referees") {
    const referees = (value as
      { name: string; email: string; relationship: string }[] | undefined) ?? [
      { name: "", email: "", relationship: "" },
      { name: "", email: "", relationship: "" },
    ];
    const change = (i: number, patch: Record<string, string>) =>
      onChange(referees.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    return (
      <div className="space-y-2">
        <p className="text-sm font-medium">{field.label}</p>
        {referees.map((r, i) => (
          <div key={i} className="grid gap-2 sm:grid-cols-3">
            <TextField
              label={t("recruitment.refereeName", { n: i + 1 })}
              value={r.name}
              onChange={(e) => change(i, { name: e.target.value })}
            />
            <TextField
              label={t("recruitment.refereeEmail", { n: i + 1 })}
              type="email"
              value={r.email}
              onChange={(e) => change(i, { email: e.target.value })}
            />
            <TextField
              label={t("recruitment.refereeRelationship", { n: i + 1 })}
              value={r.relationship}
              onChange={(e) => change(i, { relationship: e.target.value })}
            />
          </div>
        ))}
        {error ? <p className="text-xs text-danger">{error}</p> : null}
      </div>
    );
  }
  if (field.type === "checkbox" || field.type === "consent") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
        {field.label}
        {error ? <span className="text-xs text-danger">{error}</span> : null}
      </label>
    );
  }
  if (field.type === "select") {
    return (
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">{field.label}</span>
        <select
          required={field.required}
          className="h-10 rounded-md border border-field bg-surface px-3 text-sm"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="" />
          {(field.options ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
        {error ? <span className="text-xs text-danger">{error}</span> : null}
      </label>
    );
  }
  const inputType =
    { email: "email", phone: "tel", number: "number", date: "date" }[field.type] ?? "text";
  if (field.type === "textarea") {
    return (
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">{field.label}</span>
        <textarea
          className="rounded-md border border-field bg-surface px-3 py-2"
          rows={4}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
    );
  }
  return (
    <TextField
      label={field.label}
      type={inputType}
      required={field.required}
      error={error}
      value={(value as string) ?? ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** A family answers a waitlist offer at ``/offers/<token>`` (FR-17-6). */
export function OfferPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const offer = useQuery({
    queryKey: ["offer", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/offers/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const respond = useMutation({
    mutationFn: async (accept: boolean) =>
      unwrap(
        await api.POST("/api/v1/public/offers/{token}", {
          params: { path: { token } },
          body: { accept },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["offer", token], data),
  });
  if (offer.isError) return <PublicLayout title={t("leads.offerMissing")}>{null}</PublicLayout>;
  if (!offer.data) return <Spinner label={t("grid.loading")} />;
  const o = offer.data;
  return (
    <PublicLayout title={t("leads.offerTitle", { student: o.student })}>
      <p>{o.details}</p>
      {o.status === "offered" ? (
        <>
          {o.expires_at ? (
            <p className="mt-2 text-sm text-muted-foreground">
              {t("leads.offerUntil", { date: formatDateTime(o.expires_at) })}
            </p>
          ) : null}
          <div className="mt-4 flex gap-2">
            <Button onClick={() => respond.mutate(true)}>{t("leads.accept")}</Button>
            <Button variant="secondary" onClick={() => respond.mutate(false)}>
              {t("leads.decline")}
            </Button>
          </div>
        </>
      ) : (
        <p role="status" className="mt-4">
          {t(`leads.offerStatus.${o.status}`)}
        </p>
      )}
      {respond.error ? (
        <Alert tone="danger" className="mt-4">
          {respond.error.message}
        </Alert>
      ) : null}
    </PublicLayout>
  );
}
