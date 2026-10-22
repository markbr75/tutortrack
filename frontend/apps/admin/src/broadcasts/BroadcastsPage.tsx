import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FigureStrip,
  PageHeader,
  Panel,
  PanelFooter,
  figureCell,
  RuledTable,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { AiContentHelper } from "../ai/AiParts";
import { useIsPhone } from "../billing/useIsPhone";

type Broadcast = components["schemas"]["Broadcast"];
type Definition = components["schemas"]["SegmentDefinition"];
type Preview = components["schemas"]["AudiencePreview"];
type Recipient = components["schemas"]["BroadcastRecipient"];
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
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {options.map((o) => (
          <label key={o.value} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
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
  hint,
  rows = 6,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  hint?: string;
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
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-field bg-surface px-3 py-2 text-sm aria-[invalid=true]:border-danger"
      />
      {hint && !error ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
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
    <div role="status" className="rounded-md border border-border px-4 py-3 text-sm">
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

function Composer({
  onCreated,
  onCancel,
}: {
  onCreated: (b: Broadcast) => void;
  onCancel: () => void;
}) {
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
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.focus(), []);
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
    <Panel title={t("broadcasts.new")} flush>
      <form
        aria-label={t("broadcasts.new")}
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <div className="divide-y divide-rule">
          <div className="grid gap-3 px-5 py-4 sm:grid-cols-3">
            <TextField
              ref={first}
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
          <div className="px-5 py-4">
            <fieldset className="space-y-4">
              <legend className="mb-3 text-sm font-semibold">{t("broadcasts.who")}</legend>
              <div className="grid gap-3 sm:grid-cols-2">
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
                ) : null}
              </div>
              {!segment ? (
                <>
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
                        className="size-4"
                        checked={primary}
                        onChange={(e) => setPrimary(e.target.checked)}
                      />
                      {t("broadcasts.primaryOnly")}
                    </label>
                  ) : null}
                </>
              ) : null}
              <Button
                type="button"
                size="sm"
                variant="secondary"
                loading={check.isPending}
                onClick={() => check.mutate()}
              >
                {t("broadcasts.checkAudience")}
              </Button>
              {check.data ? <AudienceSummary preview={check.data} /> : null}
            </fieldset>
          </div>
          <div className="space-y-3 px-5 py-4">
            {channel === "whatsapp" ? (
              <div className="max-w-sm">
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
              </div>
            ) : (
              <>
                <AiContentHelper
                  kind="broadcast"
                  channel={channel === "sms" ? "sms" : "email"}
                  title={name}
                  onUse={(draft) => {
                    if (draft.subject) setSubject(draft.subject);
                    setBody(draft.body);
                  }}
                />
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
                  hint={t("broadcasts.variables", {
                    list: "{{ recipient.first_name }}, {{ recipient.name }}, {{ organisation.name }}",
                  })}
                  onChange={setBody}
                />
              </>
            )}
            {create.error && !Object.keys(errors).length ? (
              <Alert tone="danger">{create.error.message}</Alert>
            ) : null}
          </div>
        </div>
        <PanelFooter>
          <Button type="submit" size="sm" loading={create.isPending}>
            {t("broadcasts.saveDraft")}
          </Button>
          <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
        </PanelFooter>
      </form>
    </Panel>
  );
}

const STAT_KEYS = ["recipients", "queued", "skipped", "delivered", "opened", "clicked", "bounced",
  "unsubscribed"] as const; // prettier-ignore

function Detail({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canSend = usePermission("comms.broadcast.send");
  const phone = useIsPhone();
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
  if (!broadcast.data) return <Spinner label={t("grid.loading")} />;
  const b = broadcast.data;
  const outcome = (r: Recipient) =>
    r.status === "skipped"
      ? t(`broadcasts.skip.${r.skip_reason}`, { count: 1 })
      : r.message_status
        ? t(`designS8.messageStatus.${r.message_status}`, { defaultValue: r.message_status })
        : t(`broadcasts.recipientStatus.${r.status}`);
  const actions = canSend ? (
    <>
      {b.status === "scheduled" || b.status === "sending" ? (
        <Button size="sm" variant="secondary" onClick={() => act.mutate("pause")}>
          {t("broadcasts.pause")}
        </Button>
      ) : null}
      {b.status === "paused" ? (
        <Button size="sm" variant="secondary" onClick={() => act.mutate("resume")}>
          {t("broadcasts.resume")}
        </Button>
      ) : null}
      {LIVE.includes(b.status) ? (
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          onClick={() => act.mutate("cancel")}
        >
          {t("broadcasts.cancel")}
        </Button>
      ) : null}
    </>
  ) : null;
  return (
    <Panel
      title={b.name}
      titleId="broadcast-title"
      description={
        <>
          <span className={b.status === "failed" ? "font-medium text-danger" : undefined}>
            {t(`broadcasts.status.${b.status}`)}
          </span>
          {" · "}
          {[
            t(`comms.channel.${b.channel}`),
            t(`broadcasts.purposes.${b.purpose}`),
            b.segment_name,
            b.scheduled_for
              ? t("broadcasts.scheduledFor", {
                  when: formatDateTime(b.scheduled_for, i18n.language),
                })
              : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </>
      }
      flush
    >
      <div className="divide-y divide-rule">
        {preview.data ? (
          <figure className="px-5 py-4 text-sm">
            <figcaption className="mb-1.5 text-xs font-semibold text-muted-foreground">
              {t("broadcasts.preview")}
            </figcaption>
            <div className="max-w-2xl rounded-md border border-border px-4 py-3">
              {preview.data.subject ? (
                <p className="mb-1 font-semibold">{preview.data.subject}</p>
              ) : null}
              <p className="whitespace-pre-wrap">{preview.data.body}</p>
            </div>
          </figure>
        ) : null}
        {b.status !== "draft" ? (
          <div className="px-5">
            <FigureStrip
              label={t("designS8.broadcasts.figures")}
              className="border-0"
              figures={STAT_KEYS.map((k) => ({
                key: k,
                label: t(`broadcasts.stats.${k}`),
                value: b.stats[k],
              }))}
            />
          </div>
        ) : null}
        {canSend && b.status === "draft" ? (
          <form
            className="flex flex-wrap items-start gap-2 px-5 py-4"
            aria-label={t("broadcasts.sendNow")}
            onSubmit={(e) => {
              e.preventDefault();
              act.mutate("schedule");
            }}
          >
            <TextField
              label={t("broadcasts.sendAt")}
              type="datetime-local"
              className="tabular-nums"
              value={when}
              hint={t("broadcasts.sendAtHint")}
              onChange={(e) => setWhen(e.target.value)}
            />
            <Button type="submit" className="sm:mt-6" loading={act.isPending}>
              {when ? t("broadcasts.schedule") : t("broadcasts.sendNow")}
            </Button>
          </form>
        ) : null}
        {act.error ? (
          <div className="px-5 py-4">
            <Alert tone="danger">{act.error.message}</Alert>
          </div>
        ) : null}
        {recipients.data?.results.length ? (
          <div>
            <h3 className="px-5 pt-3.5 pb-1 text-sm font-semibold">{t("broadcasts.recipients")}</h3>
            <RuledTable
              caption={t("broadcasts.recipients")}
              columns={[
                { header: t("broadcasts.person") },
                ...(phone ? [] : [{ header: t("broadcasts.address") }]),
                { header: t("broadcasts.outcome") },
              ]}
            >
              {recipients.data.results.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.name}
                    {phone && r.address ? (
                      <span className="block text-xs break-all text-muted-foreground">
                        {r.address}
                      </span>
                    ) : null}
                  </td>
                  {phone ? null : (
                    <td className="break-all">
                      {r.address || <span className="text-muted-foreground">–</span>}
                    </td>
                  )}
                  <td
                    className={
                      r.status === "skipped"
                        ? "text-muted-foreground"
                        : r.status === "failed" ||
                            ["bounced", "complained", "failed"].includes(r.message_status)
                          ? "font-medium text-danger"
                          : undefined
                    }
                  >
                    {outcome(r)}
                  </td>
                </tr>
              ))}
            </RuledTable>
          </div>
        ) : null}
      </div>
      {actions && (b.status === "scheduled" || b.status === "sending" || b.status === "paused") ? (
        <PanelFooter>{actions}</PanelFooter>
      ) : null}
    </Panel>
  );
}

/** Broadcasts to segments (E13-T10): compose, check who it reaches, schedule, and follow
 * delivery, opens and clicks. Sending runs as a workflow in throttled batches. */
export function BroadcastsPage() {
  const { t, i18n } = useTranslation();
  const canSend = usePermission("comms.broadcast.send");
  const phone = useIsPhone();
  const queryClient = useQueryClient();
  const [composing, setComposing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["broadcasts"],
    queryFn: async () => unwrap(await api.GET("/api/v1/broadcasts", { params: { query: PAGE } })),
  });
  const rows = list.data?.results ?? [];
  const when = (b: Broadcast) =>
    formatDateTime(b.finished_at ?? b.scheduled_for ?? b.created_at, i18n.language);
  return (
    <section>
      <PageHeader
        title={t("broadcasts.title")}
        description={t("broadcasts.help")}
        actions={
          canSend ? (
            <Button onClick={() => setComposing((v) => !v)} aria-expanded={composing}>
              {t("broadcasts.new")}
            </Button>
          ) : null
        }
      />
      <div className="space-y-6">
        {composing ? (
          <Composer
            onCancel={() => setComposing(false)}
            onCreated={(b) => {
              setComposing(false);
              setSelected(b.id);
              void queryClient.invalidateQueries({ queryKey: ["broadcasts"] });
            }}
          />
        ) : null}
        {list.isPending ? (
          <Spinner label={t("grid.loading")} />
        ) : (
          <RuledTable
            framed
            caption={t("broadcasts.title")}
            empty={rows.length ? undefined : t("broadcasts.none")}
            columns={[
              { header: t("broadcasts.name") },
              ...(phone
                ? []
                : [{ header: t("broadcasts.channel") }, { header: t("broadcasts.statusLabel") }]),
              { header: t("broadcasts.stats.recipients"), end: true },
              ...(phone
                ? []
                : [
                    { header: t("broadcasts.stats.opened"), end: true },
                    { header: t("broadcasts.when") },
                  ]),
            ]}
          >
            {rows.map((b) => (
              <tr key={b.id} className={selected === b.id ? "bg-muted/60" : undefined}>
                <td>
                  <button
                    type="button"
                    className="text-left font-medium underline-offset-2 hover:underline"
                    onClick={() => setSelected(b.id)}
                    aria-pressed={selected === b.id}
                  >
                    {b.name}
                  </button>
                  {phone ? (
                    <span className="block text-xs text-muted-foreground tabular-nums">
                      {[
                        t(`comms.channel.${b.channel}`),
                        t(`broadcasts.status.${b.status}`),
                        when(b),
                      ].join(" · ")}
                    </span>
                  ) : null}
                </td>
                {phone ? null : (
                  <>
                    <td>{t(`comms.channel.${b.channel}`)}</td>
                    <td
                      className={
                        b.status === "draft" || b.status === "cancelled"
                          ? "text-muted-foreground"
                          : b.status === "failed"
                            ? "font-medium text-danger"
                            : undefined
                      }
                    >
                      {t(`broadcasts.status.${b.status}`)}
                    </td>
                  </>
                )}
                <td className={figureCell}>{b.stats.recipients}</td>
                {phone ? null : (
                  <>
                    <td className={figureCell}>
                      {b.channel === "email" ? (
                        b.stats.opened
                      ) : (
                        <span className="text-muted-foreground">–</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap tabular-nums">{when(b)}</td>
                  </>
                )}
              </tr>
            ))}
          </RuledTable>
        )}
        {selected ? <Detail key={selected} id={selected} /> : null}
      </div>
    </section>
  );
}
