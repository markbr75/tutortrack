import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { api, fieldErrors, usePermission } from "../api";

type Broadcast = components["schemas"]["Broadcast"];
type Definition = components["schemas"]["SegmentDefinition"];
type Preview = components["schemas"]["AudiencePreview"];
type Channel = "email" | "sms" | "whatsapp";
type Purpose = "operational" | "marketing";
type Audience = "contacts" | "tutors";

const PAGE = { page_size: 100 };
const LIVE = ["scheduled", "sending", "paused"];

function Checkboxes({
  legend,
  options,
  value,
  onChange,
}: {
  legend: string;
  options: { value: string; name: string }[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  if (!options.length) return null;
  return (
    <fieldset className="space-y-1">
      <legend className="text-sm font-medium">{legend}</legend>
      <div className="flex flex-wrap gap-3">
        {options.map((o) => (
          <label key={o.value} className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              checked={value.includes(o.value)}
              onChange={(e) =>
                onChange(
                  e.target.checked ? [...value, o.value] : value.filter((v) => v !== o.value),
                )
              }
            />
            {o.name}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function TextArea({
  label,
  value,
  onChange,
  error,
  rows = 6,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  rows?: number;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        rows={rows}
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-background p-2 text-sm"
      />
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Who a broadcast reaches now and why some people are skipped (FR-13-6). */
function AudienceSummary({ preview }: { preview: Preview }) {
  const { t } = useTranslation();
  return (
    <div role="status" className="rounded-md border border-border p-3 text-sm">
      <p className="font-medium">
        {t("broadcasts.reach", { sendable: preview.sendable, total: preview.total })}
      </p>
      {Object.keys(preview.skipped).length ? (
        <ul className="mt-1 list-disc pl-5">
          {Object.entries(preview.skipped).map(([reason, count]) => (
            <li key={reason}>{t(`broadcasts.skip.${reason}`, { count })}</li>
          ))}
        </ul>
      ) : null}
      {preview.sample.length ? (
        <p className="mt-1 text-muted-foreground">
          {t("broadcasts.sample", { names: preview.sample.map((s) => s.name).join(", ") })}
        </p>
      ) : null}
    </div>
  );
}

function Composer({ onCreated }: { onCreated: (b: Broadcast) => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [channel, setChannel] = useState<Channel>("email");
  const [purpose, setPurpose] = useState<Purpose>("operational");
  const [audience, setAudience] = useState<Audience>("contacts");
  const [segment, setSegment] = useState("");
  const [statuses, setStatuses] = useState<string[]>(["active"]);
  const [tags, setTags] = useState<string[]>([]);
  const [primary, setPrimary] = useState(true);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [template, setTemplate] = useState("");
  const options = useQuery({
    queryKey: ["segments", "options"],
    queryFn: async () => unwrap(await api.GET("/api/v1/segments/options")),
  });
  const saved = useQuery({
    queryKey: ["segments"],
    queryFn: async () => unwrap(await api.GET("/api/v1/segments", { params: { query: PAGE } })),
  });
  const templates = useQuery({
    queryKey: ["whatsapp-templates"],
    enabled: channel === "whatsapp",
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/whatsapp-templates", { params: { query: PAGE } })),
  });
  const definition: Definition =
    audience === "contacts"
      ? { client_statuses: statuses, tags, contacts: primary ? "primary" : "all" }
      : { tutor_statuses: statuses, tags };
  const chosenSegment = saved.data?.results.find((s) => s.id === segment);
  const check = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/segments/preview", {
          body: {
            audience: chosenSegment?.audience ?? audience,
            definition: chosenSegment?.definition ?? definition,
            channel,
            purpose,
          },
        }),
      ),
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/broadcasts", {
          body: {
            name,
            channel,
            purpose,
            subject,
            body,
            audience,
            segment: segment || null,
            definition: segment ? {} : definition,
            whatsapp_template: channel === "whatsapp" && template ? template : null,
          },
        }),
      ),
    onSuccess: onCreated,
  });
  const errors = fieldErrors(create.error);
  const statusOptions =
    audience === "contacts"
      ? (options.data?.client_statuses ?? [])
      : (options.data?.tutor_statuses ?? []);
  return (
    <form
      aria-label={t("broadcasts.new")}
      className="space-y-4 rounded-md border border-border p-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <h2 className="font-semibold">{t("broadcasts.new")}</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <TextField
          label={t("broadcasts.name")}
          value={name}
          required
          error={errors.name}
          onChange={(e) => setName(e.target.value)}
        />
        <SelectField
          label={t("broadcasts.channel")}
          value={channel}
          onChange={(e) => setChannel(e.target.value as Channel)}
          options={(["email", "sms", "whatsapp"] as const).map((c) => ({
            value: c,
            label: t(`comms.channel.${c}`),
          }))}
        />
        <SelectField
          label={t("broadcasts.purpose")}
          value={purpose}
          hint={t(`broadcasts.purposeHint.${purpose}`)}
          onChange={(e) => setPurpose(e.target.value as Purpose)}
          options={(["operational", "marketing"] as const).map((p) => ({
            value: p,
            label: t(`broadcasts.purposes.${p}`),
          }))}
        />
      </div>
      <fieldset className="space-y-3">
        <legend className="font-medium">{t("broadcasts.who")}</legend>
        <SelectField
          label={t("broadcasts.segment")}
          value={segment}
          onChange={(e) => setSegment(e.target.value)}
          options={[
            { value: "", label: t("broadcasts.buildSegment") },
            ...(saved.data?.results ?? []).map((s) => ({ value: s.id, label: s.name })),
          ]}
        />
        {!segment ? (
          <div className="space-y-3">
            <SelectField
              label={t("broadcasts.audience")}
              value={audience}
              onChange={(e) => {
                setAudience(e.target.value as Audience);
                setStatuses(["active"]);
              }}
              options={(["contacts", "tutors"] as const).map((a) => ({
                value: a,
                label: t(`broadcasts.audiences.${a}`),
              }))}
            />
            <Checkboxes
              legend={t("broadcasts.statuses")}
              options={statusOptions}
              value={statuses}
              onChange={setStatuses}
            />
            <Checkboxes
              legend={t("broadcasts.tags")}
              options={options.data?.tags ?? []}
              value={tags}
              onChange={setTags}
            />
            {audience === "contacts" ? (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={primary}
                  onChange={(e) => setPrimary(e.target.checked)}
                />
                {t("broadcasts.primaryOnly")}
              </label>
            ) : null}
          </div>
        ) : null}
        <Button type="button" variant="secondary" onClick={() => check.mutate()}>
          {t("broadcasts.checkAudience")}
        </Button>
        {check.data ? <AudienceSummary preview={check.data} /> : null}
      </fieldset>
      {channel === "whatsapp" ? (
        <SelectField
          label={t("broadcasts.template")}
          value={template}
          error={errors.whatsapp_template}
          onChange={(e) => setTemplate(e.target.value)}
          options={[
            { value: "", label: t("broadcasts.chooseTemplate") },
            ...(templates.data?.results ?? [])
              .filter((tpl) => tpl.status === "approved")
              .map((tpl) => ({ value: tpl.id, label: tpl.name })),
          ]}
        />
      ) : (
        <div className="space-y-3">
          {channel === "email" ? (
            <TextField
              label={t("broadcasts.subject")}
              value={subject}
              error={errors.subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          ) : null}
          <TextArea
            label={t("broadcasts.body")}
            value={body}
            error={errors.body}
            onChange={setBody}
          />
          <p className="text-xs text-muted-foreground">
            {t("broadcasts.variables", {
              list: "{{ recipient.first_name }}, {{ recipient.name }}, {{ organisation.name }}",
            })}
          </p>
        </div>
      )}
      {create.error && !Object.keys(errors).length ? (
        <Alert tone="danger">{create.error.message}</Alert>
      ) : null}
      <Button type="submit" disabled={create.isPending}>
        {t("broadcasts.saveDraft")}
      </Button>
    </form>
  );
}

function Stats({ broadcast }: { broadcast: Broadcast }) {
  const { t } = useTranslation();
  const keys = ["recipients", "queued", "skipped", "delivered", "opened", "clicked", "bounced",
    "unsubscribed"] as const; // prettier-ignore
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {keys.map((k) => (
        <div key={k} className="rounded-md border border-border p-2">
          <dt className="text-xs text-muted-foreground">{t(`broadcasts.stats.${k}`)}</dt>
          <dd className="text-lg font-semibold">{broadcast.stats[k]}</dd>
        </div>
      ))}
    </dl>
  );
}

function Detail({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canSend = usePermission("comms.broadcast.send");
  const [when, setWhen] = useState("");
  const path = { params: { path: { id } } };
  const broadcast = useQuery({
    queryKey: ["broadcasts", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/broadcasts/{id}", path)),
  });
  const recipients = useQuery({
    queryKey: ["broadcasts", id, "recipients"],
    enabled: Boolean(broadcast.data && broadcast.data.status !== "draft"),
    queryFn: async () => unwrap(await api.GET("/api/v1/broadcasts/{id}/recipients", path)),
  });
  const preview = useQuery({
    queryKey: ["broadcasts", id, "preview"],
    queryFn: async () => unwrap(await api.POST("/api/v1/broadcasts/{id}/preview", path)),
  });
  const done = () => void queryClient.invalidateQueries({ queryKey: ["broadcasts"] });
  const act = useMutation({
    mutationFn: async (action: "schedule" | "pause" | "resume" | "cancel") => {
      if (action === "schedule") {
        return unwrap(
          await api.POST("/api/v1/broadcasts/{id}/schedule", {
            ...path,
            body: { scheduled_for: when ? new Date(when).toISOString() : null },
          }),
        );
      }
      const url = `/api/v1/broadcasts/{id}/${action}` as const;
      return unwrap(await api.POST(url, path));
    },
    onSuccess: done,
  });
  if (!broadcast.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const b = broadcast.data;
  return (
    <section aria-labelledby="broadcast-title" className="space-y-4 rounded-md border p-4">
      <h2 id="broadcast-title" className="text-lg font-semibold">
        {b.name} · {t(`broadcasts.status.${b.status}`)}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t(`comms.channel.${b.channel}`)} · {t(`broadcasts.purposes.${b.purpose}`)}
        {b.segment_name ? ` · ${b.segment_name}` : ""}
        {b.scheduled_for
          ? ` · ${t("broadcasts.scheduledFor", { when: formatDateTime(b.scheduled_for, i18n.language) })}`
          : ""}
      </p>
      {preview.data ? (
        <figure className="rounded-md bg-muted p-3 text-sm">
          <figcaption className="text-xs text-muted-foreground">
            {t("broadcasts.preview")}
          </figcaption>
          {preview.data.subject ? <p className="font-medium">{preview.data.subject}</p> : null}
          <p className="whitespace-pre-wrap">{preview.data.body}</p>
        </figure>
      ) : null}
      {b.status !== "draft" ? <Stats broadcast={b} /> : null}
      {canSend ? (
        <div className="flex flex-wrap items-end gap-2">
          {b.status === "draft" ? (
            <>
              <TextField
                label={t("broadcasts.sendAt")}
                type="datetime-local"
                value={when}
                hint={t("broadcasts.sendAtHint")}
                onChange={(e) => setWhen(e.target.value)}
              />
              <Button onClick={() => act.mutate("schedule")} disabled={act.isPending}>
                {when ? t("broadcasts.schedule") : t("broadcasts.sendNow")}
              </Button>
            </>
          ) : null}
          {b.status === "scheduled" || b.status === "sending" ? (
            <Button variant="secondary" onClick={() => act.mutate("pause")}>
              {t("broadcasts.pause")}
            </Button>
          ) : null}
          {b.status === "paused" ? (
            <Button variant="secondary" onClick={() => act.mutate("resume")}>
              {t("broadcasts.resume")}
            </Button>
          ) : null}
          {LIVE.includes(b.status) ? (
            <Button variant="ghost" onClick={() => act.mutate("cancel")}>
              {t("broadcasts.cancel")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
      {recipients.data?.results.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="mb-2 text-left font-semibold">{t("broadcasts.recipients")}</caption>
            <thead>
              <tr className="text-left">
                <th scope="col">{t("broadcasts.person")}</th>
                <th scope="col">{t("broadcasts.address")}</th>
                <th scope="col">{t("broadcasts.outcome")}</th>
              </tr>
            </thead>
            <tbody>
              {recipients.data.results.map((r) => (
                <tr key={r.id} className="border-t border-border">
                  <td>{r.name}</td>
                  <td>{r.address}</td>
                  <td>
                    {r.status === "skipped"
                      ? t(`broadcasts.skip.${r.skip_reason}`, { count: 1 })
                      : r.message_status || t(`broadcasts.recipientStatus.${r.status}`)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

/** Broadcasts to segments (E13-T10): compose, check who it reaches, schedule, and follow
 * delivery, opens and clicks. Sending runs as a workflow in throttled batches. */
export function BroadcastsPage() {
  const { t, i18n } = useTranslation();
  const canSend = usePermission("comms.broadcast.send");
  const queryClient = useQueryClient();
  const [composing, setComposing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["broadcasts"],
    queryFn: async () => unwrap(await api.GET("/api/v1/broadcasts", { params: { query: PAGE } })),
  });
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t("broadcasts.title")}</h1>
        {canSend ? (
          <Button onClick={() => setComposing((v) => !v)} aria-expanded={composing}>
            {t("broadcasts.new")}
          </Button>
        ) : null}
      </div>
      <p className="text-sm text-muted-foreground">{t("broadcasts.help")}</p>
      {composing ? (
        <Composer
          onCreated={(b) => {
            setComposing(false);
            setSelected(b.id);
            void queryClient.invalidateQueries({ queryKey: ["broadcasts"] });
          }}
        />
      ) : null}
      {list.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : !list.data?.results.length ? (
        <p className="text-sm text-muted-foreground">{t("broadcasts.none")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("broadcasts.title")}</caption>
            <thead>
              <tr className="text-left">
                <th scope="col">{t("broadcasts.name")}</th>
                <th scope="col">{t("broadcasts.channel")}</th>
                <th scope="col">{t("broadcasts.statusLabel")}</th>
                <th scope="col">{t("broadcasts.stats.recipients")}</th>
                <th scope="col">{t("broadcasts.stats.opened")}</th>
                <th scope="col">{t("broadcasts.when")}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.results.map((b) => (
                <tr key={b.id} className="border-t border-border">
                  <td>
                    <button
                      type="button"
                      className="text-left underline"
                      onClick={() => setSelected(b.id)}
                      aria-pressed={selected === b.id}
                    >
                      {b.name}
                    </button>
                  </td>
                  <td>{t(`comms.channel.${b.channel}`)}</td>
                  <td>{t(`broadcasts.status.${b.status}`)}</td>
                  <td>{b.stats.recipients}</td>
                  <td>{b.channel === "email" ? b.stats.opened : "—"}</td>
                  <td>
                    {formatDateTime(
                      b.finished_at ?? b.scheduled_for ?? b.created_at,
                      i18n.language,
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected ? <Detail id={selected} /> : null}
    </section>
  );
}
