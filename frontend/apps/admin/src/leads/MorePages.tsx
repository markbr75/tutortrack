import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { Turnstile } from "../components/Turnstile";
import { PublicLayout } from "../layout/PublicLayout";
import { LeadsPage } from "./LeadsPages";

type FormDef = components["schemas"]["Form"];

export interface Field {
  key: string;
  label: string;
  type: string;
  required?: boolean;
  options?: string[];
  maps_to?: string;
  show_if?: { field: string; equals: unknown };
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
                     "checkbox", "consent", "postcode", "students"]; // prettier-ignore
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
    <LeadsPage title={t("leads.forms")}>
      <Button onClick={() => create.mutate()}>{t("leads.newForm")}</Button>
      <ul className="divide-y divide-border rounded-md border border-border text-sm">
        {forms.data?.map((f) => (
          <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
            <span>
              {f.name} · {t(`leads.formTypes.${f.type ?? "enquiry"}`)} ·{" "}
              {f.published ? t("leads.published") : t("leads.draft")}
            </span>
            <span className="flex gap-2">
              {f.published ? (
                <a className="underline" href={`/f/${f.slug}`}>
                  {t("leads.openForm")}
                </a>
              ) : null}
              <Button size="sm" variant="ghost" onClick={() => setEditing(f)}>
                {t("leads.edit")}
              </Button>
            </span>
          </li>
        ))}
      </ul>
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
  const remove = (step: number, index: number) =>
    setSchema({
      steps: schema.steps.map((s, i) =>
        i !== step ? s : { ...s, fields: s.fields.filter((_, j) => j !== index) },
      ),
    });
  return (
    <section
      aria-label={t("leads.editForm")}
      className="space-y-3 rounded-md border border-border p-4"
    >
      <div className="flex flex-wrap gap-2">
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
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={published}
            onChange={(e) => setPublished(e.target.checked)}
          />
          {t("leads.publish")}
        </label>
      </div>
      {schema.steps.map((step, s) => (
        <fieldset key={s} className="space-y-2 rounded-md border border-border p-3">
          <legend className="px-1 text-sm font-medium">{step.title}</legend>
          {step.fields.map((f, i) => (
            <div key={i} className="flex flex-wrap items-end gap-2 text-sm">
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
                  className="h-10 rounded-md border border-border bg-background px-2"
                  value={f.type}
                  onChange={(e) => update(s, i, { type: e.target.value })}
                >
                  {FIELD_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="font-medium">{t("leads.fieldMapsTo")}</span>
                <select
                  className="h-10 rounded-md border border-border bg-background px-2"
                  value={f.maps_to ?? ""}
                  onChange={(e) => update(s, i, { maps_to: e.target.value || undefined })}
                >
                  {MAPPINGS.map((m) => (
                    <option key={m} value={m}>
                      {m || t("leads.notMapped")}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={Boolean(f.required)}
                  onChange={(e) => update(s, i, { required: e.target.checked })}
                />
                {t("leads.required")}
              </label>
              <Button size="sm" variant="ghost" onClick={() => remove(s, i)}>
                {t("leads.removeField")}
              </Button>
            </div>
          ))}
          <Button size="sm" variant="secondary" onClick={() => add(s)}>
            {t("leads.addField")}
          </Button>
        </fieldset>
      ))}
      <div className="flex gap-2">
        <Button onClick={() => save.mutate()} loading={save.isPending}>
          {t("common.save")}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          {t("common.cancel")}
        </Button>
      </div>
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
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
      {entries.data && !entries.data.results.length ? (
        <p className="text-sm">{t("leads.nobodyWaiting")}</p>
      ) : null}
      <ul className="space-y-2">
        {entries.data?.results.map((entry) => (
          <li
            key={entry.id}
            className="flex flex-wrap items-end gap-2 rounded-md border border-border p-3 text-sm"
          >
            <span className="min-w-48">
              #{entry.position} · <strong>{entry.student_name}</strong> · {entry.subject || "–"} ·{" "}
              {t("leads.since", { date: formatDate(entry.created_at) })}
            </span>
            <TextField
              label={t("leads.offerDetails")}
              value={details[entry.id] ?? ""}
              onChange={(e) => setDetails({ ...details, [entry.id]: e.target.value })}
            />
            <Button size="sm" disabled={!details[entry.id]} onClick={() => offer.mutate(entry.id)}>
              {t("leads.offerPlace")}
            </Button>
          </li>
        ))}
      </ul>
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
  if (!report.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const r = report.data;
  return (
    <LeadsPage title={t("leads.reports")}>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          [t("leads.enquiries"), String(r.total)],
          [t("leads.winRate"), `${r.win_rate}%`],
          [
            t("leads.firstResponse"),
            r.first_response_hours === null
              ? "–"
              : t("leads.hours", { count: r.first_response_hours }),
          ],
        ].map(([label, value]) => (
          <div key={label} className="rounded-md border border-border p-3">
            <dt className="text-sm text-muted-foreground">{label}</dt>
            <dd className="text-xl font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="text-left font-semibold">{t("leads.byStage")}</caption>
          <thead>
            <tr className="text-left">
              <th scope="col">{t("leads.stage")}</th>
              <th scope="col">{t("leads.reached")}</th>
              <th scope="col">%</th>
            </tr>
          </thead>
          <tbody>
            {r.stages.map((s) => (
              <tr key={s.stage} className="border-t border-border">
                <td>{s.stage}</td>
                <td>{s.reached}</td>
                <td>{s.rate}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="text-left font-semibold">{t("leads.bySource")}</caption>
          <thead>
            <tr className="text-left">
              <th scope="col">{t("leads.source")}</th>
              <th scope="col">{t("leads.enquiries")}</th>
              <th scope="col">{t("leads.won")}</th>
            </tr>
          </thead>
          <tbody>
            {r.by_source.map((row) => (
              <tr key={row.key} className="border-t border-border">
                <td>{t(`leads.sources.${row.key}`, { defaultValue: row.key })}</td>
                <td>{row.total}</td>
                <td>{row.won}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </LeadsPage>
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
  if (!form.data) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
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
              <legend className="text-lg font-semibold">{step.title}</legend>
              {step.fields
                .filter((f) => !f.show_if || answers[f.show_if.field] === f.show_if.equals)
                .map((f) => (
                  <PublicField
                    key={f.key}
                    field={f}
                    value={answers[f.key]}
                    error={errors?.[f.key]?.[0]}
                    onChange={(v) => set(f.key, v)}
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
          {form.data.consent_text ? <p className="text-sm">{form.data.consent_text}</p> : null}
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
}: {
  field: Field;
  value: unknown;
  error?: string;
  onChange: (value: unknown) => void;
}) {
  const { t } = useTranslation();
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
        {error ? <p className="text-sm text-danger">{error}</p> : null}
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
        {error ? <p className="text-sm text-danger">{error}</p> : null}
      </div>
    );
  }
  if (field.type === "checkbox" || field.type === "consent") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
        {field.label}
        {error ? <span className="text-danger">{error}</span> : null}
      </label>
    );
  }
  if (field.type === "select") {
    return (
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">{field.label}</span>
        <select
          required={field.required}
          className="h-10 rounded-md border border-border bg-background px-2"
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
        {error ? <span className="text-danger">{error}</span> : null}
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
          className="rounded-md border border-border p-2"
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
  if (!offer.data) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  const o = offer.data;
  return (
    <PublicLayout title={t("leads.offerTitle", { student: o.student })}>
      <p>{o.details}</p>
      {o.status === "offered" ? (
        <>
          {o.expires_at ? (
            <p className="text-sm">
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
      {respond.error ? <Alert tone="danger">{respond.error.message}</Alert> : null}
    </PublicLayout>
  );
}
