import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, fieldErrors } from "../api";

const PAGE = { params: { query: { page_size: 100 } } };
type Tab = "domains" | "numbers" | "whatsapp" | "canned" | "marketing";

function Form({
  title,
  submit,
  pending,
  onSubmit,
  children,
}: {
  title: string;
  submit: string;
  pending?: boolean;
  onSubmit: () => void;
  children: ReactNode;
}) {
  return (
    <form
      aria-label={title}
      className="space-y-3 rounded-md border border-border p-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h3 className="font-semibold">{title}</h3>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
      <Button type="submit" disabled={pending}>
        {submit}
      </Button>
    </form>
  );
}

function Problem({ error }: { error: Error | null }) {
  return error ? <Alert tone="danger">{error.message}</Alert> : null;
}

/** Custom sending domains (FR-13-1): add, publish the DNS records, check. */
function SenderDomains() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [domain, setDomain] = useState("");
  const [local, setLocal] = useState("hello");
  const rows = useQuery({
    queryKey: ["sender-domains"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sender-domains", PAGE)),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["sender-domains"] });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/sender-domains", { body: { domain, local_part: local } })),
    onSuccess: () => {
      setDomain("");
      refresh();
    },
  });
  const check = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/sender-domains/{id}/check", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  const makeDefault = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.PATCH("/api/v1/sender-domains/{id}", {
          params: { path: { id } },
          body: { is_default: true },
        }),
      ),
    onSuccess: refresh,
  });
  const errors = fieldErrors(add.error);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("messaging.domains.help")}</p>
      {rows.data?.results.map((row) => (
        <section key={row.id} className="space-y-2 rounded-md border border-border p-3">
          <h3 className="font-semibold">
            {row.from_address} · {t(`messaging.domains.status.${row.status}`)}
            {row.is_default ? ` · ${t("messaging.domains.default")}` : ""}
          </h3>
          {row.last_checked_at ? (
            <p className="text-xs text-muted-foreground">
              {t("messaging.domains.checked", {
                when: formatDateTime(row.last_checked_at, i18n.language),
              })}
            </p>
          ) : null}
          {row.error ? <Alert tone="warning">{row.error}</Alert> : null}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="text-left text-sm font-medium">
                {t("messaging.domains.records")}
              </caption>
              <thead>
                <tr className="text-left">
                  <th scope="col">{t("messaging.domains.type")}</th>
                  <th scope="col">{t("messaging.domains.host")}</th>
                  <th scope="col">{t("messaging.domains.value")}</th>
                  <th scope="col">{t("messaging.domains.verified")}</th>
                </tr>
              </thead>
              <tbody>
                {row.dns_records.map((r) => (
                  <tr key={`${r.purpose}-${r.host}`} className="border-t border-border">
                    <td>{r.record_type}</td>
                    <td className="break-all font-mono text-xs">{r.host}</td>
                    <td className="break-all font-mono text-xs">{r.value}</td>
                    <td>
                      {["spf", "dmarc"].includes(r.purpose)
                        ? t("messaging.domains.recommended")
                        : r.verified
                          ? t("messaging.yes")
                          : t("messaging.no")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={() => check.mutate(row.id)}>
              {t("messaging.domains.check")}
            </Button>
            {row.status === "verified" && !row.is_default ? (
              <Button size="sm" variant="secondary" onClick={() => makeDefault.mutate(row.id)}>
                {t("messaging.domains.makeDefault")}
              </Button>
            ) : null}
          </div>
        </section>
      ))}
      <Form
        title={t("messaging.domains.add")}
        submit={t("messaging.domains.add")}
        pending={add.isPending}
        onSubmit={() => add.mutate()}
      >
        <TextField
          label={t("messaging.domains.domain")}
          value={domain}
          required
          error={errors.domain}
          onChange={(e) => setDomain(e.target.value)}
        />
        <TextField
          label={t("messaging.domains.localPart")}
          value={local}
          error={errors.local_part}
          onChange={(e) => setLocal(e.target.value)}
        />
      </Form>
      {!errors.domain ? <Problem error={add.error} /> : null}
    </div>
  );
}

function Numbers() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [channel, setChannel] = useState<"sms" | "whatsapp">("sms");
  const [number, setNumber] = useState("");
  const [label, setLabel] = useState("");
  const rows = useQuery({
    queryKey: ["phone-numbers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/phone-numbers", PAGE)),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["phone-numbers"] });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/phone-numbers", { body: { channel, number, label } })),
    onSuccess: () => {
      setNumber("");
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      api.DELETE("/api/v1/phone-numbers/{id}", { params: { path: { id } } }),
    onSuccess: refresh,
  });
  const errors = fieldErrors(add.error);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("messaging.numbers.help")}</p>
      <ul className="space-y-1 text-sm">
        {rows.data?.results.map((row) => (
          <li key={row.id} className="flex items-center gap-2">
            <span>
              {row.number} · {t(`comms.channel.${row.channel}`)}
              {row.label ? ` · ${row.label}` : ""}
              {row.is_default ? ` · ${t("messaging.domains.default")}` : ""}
            </span>
            <Button size="sm" variant="ghost" onClick={() => remove.mutate(row.id)}>
              {t("messaging.remove")}
            </Button>
          </li>
        ))}
      </ul>
      <Form
        title={t("messaging.numbers.add")}
        submit={t("messaging.numbers.add")}
        pending={add.isPending}
        onSubmit={() => add.mutate()}
      >
        <SelectField
          label={t("messaging.numbers.channel")}
          value={channel}
          onChange={(e) => setChannel(e.target.value as "sms" | "whatsapp")}
          options={(["sms", "whatsapp"] as const).map((c) => ({
            value: c,
            label: t(`comms.channel.${c}`),
          }))}
        />
        <TextField
          label={t("messaging.numbers.number")}
          value={number}
          required
          hint={t("messaging.numbers.numberHint")}
          error={errors.number}
          onChange={(e) => setNumber(e.target.value)}
        />
        <TextField
          label={t("messaging.numbers.label")}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
      </Form>
    </div>
  );
}

function WhatsAppTemplates() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [sid, setSid] = useState("");
  const [body, setBody] = useState("");
  const [variables, setVariables] = useState("");
  const [typeKey, setTypeKey] = useState("");
  const [status, setStatus] = useState<"pending" | "approved" | "rejected">("approved");
  const rows = useQuery({
    queryKey: ["whatsapp-templates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/whatsapp-templates", PAGE)),
  });
  const types = useQuery({
    queryKey: ["notification-settings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/notification-settings")),
  });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/whatsapp-templates", {
          body: {
            name,
            content_sid: sid,
            body,
            variables: variables.split("\n").filter((v) => v.trim()),
            type_key: typeKey,
            status,
          },
        }),
      ),
    onSuccess: () => {
      setName("");
      setBody("");
      void queryClient.invalidateQueries({ queryKey: ["whatsapp-templates"] });
    },
  });
  const errors = fieldErrors(add.error);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("messaging.whatsapp.help")}</p>
      <ul className="space-y-1 text-sm">
        {rows.data?.results.map((row) => (
          <li key={row.id}>
            <span className="font-medium">{row.name}</span> ·{" "}
            {t(`messaging.whatsapp.status.${row.status}`)}
            {row.type_key ? ` · ${row.type_key}` : ""} — {row.body}
          </li>
        ))}
      </ul>
      <Form
        title={t("messaging.whatsapp.add")}
        submit={t("messaging.whatsapp.add")}
        pending={add.isPending}
        onSubmit={() => add.mutate()}
      >
        <TextField
          label={t("messaging.whatsapp.name")}
          value={name}
          required
          error={errors.name}
          onChange={(e) => setName(e.target.value)}
        />
        <TextField
          label={t("messaging.whatsapp.sid")}
          value={sid}
          onChange={(e) => setSid(e.target.value)}
        />
        <TextField
          label={t("messaging.whatsapp.body")}
          value={body}
          required
          hint={t("messaging.whatsapp.bodyHint", { example: "{{1}}, {{2}}" })}
          error={errors.body}
          onChange={(e) => setBody(e.target.value)}
        />
        <TextField
          label={t("messaging.whatsapp.variables")}
          value={variables}
          hint={t("messaging.whatsapp.variablesHint", { example: "{{ recipient.first_name }}" })}
          error={errors.variables}
          onChange={(e) => setVariables(e.target.value.replaceAll(";", "\n"))}
        />
        <SelectField
          label={t("messaging.whatsapp.usedFor")}
          value={typeKey}
          onChange={(e) => setTypeKey(e.target.value)}
          options={[
            { value: "", label: t("messaging.whatsapp.broadcastsOnly") },
            ...(types.data ?? [])
              .filter((s) => s.available_channels.includes("whatsapp"))
              .map((s) => ({ value: s.key, label: s.label })),
          ]}
        />
        <SelectField
          label={t("messaging.whatsapp.approval")}
          value={status}
          onChange={(e) => setStatus(e.target.value as typeof status)}
          options={(["approved", "pending", "rejected"] as const).map((s) => ({
            value: s,
            label: t(`messaging.whatsapp.status.${s}`),
          }))}
        />
      </Form>
    </div>
  );
}

function CannedReplies() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const rows = useQuery({
    queryKey: ["canned-replies"],
    queryFn: async () => unwrap(await api.GET("/api/v1/canned-replies", PAGE)),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["canned-replies"] });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/canned-replies", { body: { title, body } })),
    onSuccess: () => {
      setTitle("");
      setBody("");
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      api.DELETE("/api/v1/canned-replies/{id}", { params: { path: { id } } }),
    onSuccess: refresh,
  });
  const errors = fieldErrors(add.error);
  return (
    <div className="space-y-4">
      <ul className="space-y-1 text-sm">
        {rows.data?.results.map((row) => (
          <li key={row.id} className="flex items-center gap-2">
            <span>
              <span className="font-medium">{row.title}</span> — {row.body}
            </span>
            <Button size="sm" variant="ghost" onClick={() => remove.mutate(row.id)}>
              {t("messaging.remove")}
            </Button>
          </li>
        ))}
      </ul>
      <Form
        title={t("messaging.canned.add")}
        submit={t("messaging.canned.add")}
        pending={add.isPending}
        onSubmit={() => add.mutate()}
      >
        <TextField
          label={t("messaging.canned.title")}
          value={title}
          required
          error={errors.title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <TextField
          label={t("messaging.canned.body")}
          value={body}
          required
          error={errors.body}
          onChange={(e) => setBody(e.target.value)}
        />
      </Form>
    </div>
  );
}

/** Mailchimp and Brevo (FR-13-9): connect with an API key, choose the audience, sync. */
function MarketingSync() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [keys, setKeys] = useState<Record<string, string>>({});
  const rows = useQuery({
    queryKey: ["marketing-sync"],
    queryFn: async () => unwrap(await api.GET("/api/v1/marketing-sync")),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["marketing-sync"] });
  const connect = useMutation({
    mutationFn: async (provider: string) =>
      unwrap(
        await api.POST("/api/v1/integrations/connections", {
          body: {
            provider,
            level: "organisation",
            api_key: keys[provider] ?? "",
            username: "",
            password: "",
          },
        }),
      ),
    onSuccess: refresh,
  });
  const sync = useMutation({
    mutationFn: async (provider: string) =>
      unwrap(
        await api.POST("/api/v1/marketing-sync/{provider}/sync", {
          params: { path: { provider } },
        }),
      ),
    onSuccess: refresh,
  });
  if (rows.isPending) return <Spinner label={t("grid.loading")} />;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("messaging.marketing.help")}</p>
      {rows.data?.map((row) => (
        <section key={row.provider} className="space-y-2 rounded-md border border-border p-3">
          <h3 className="font-semibold">
            {row.name}
            {row.connection ? ` · ${row.account_name || t("messaging.marketing.connected")}` : ""}
          </h3>
          {row.connection ? (
            <>
              <Audiences provider={row.provider} current={row.audience_id} onChosen={refresh} />
              {row.last_sync_at ? (
                <p className="text-xs text-muted-foreground">
                  {t("messaging.marketing.lastSync", {
                    when: formatDateTime(row.last_sync_at, i18n.language),
                  })}
                </p>
              ) : null}
              {row.error ? <Alert tone="warning">{row.error}</Alert> : null}
              {row.webhook_url ? (
                <TextField
                  label={t("marketingReturn.webhook", { name: row.name })}
                  hint={t("marketingReturn.webhookHint", { name: row.name })}
                  readOnly
                  value={row.webhook_url}
                  onFocus={(e) => e.target.select()}
                />
              ) : null}
              <Button
                size="sm"
                variant="secondary"
                disabled={!row.audience_id || sync.isPending}
                onClick={() => sync.mutate(row.provider)}
              >
                {t("messaging.marketing.syncNow")}
              </Button>
            </>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <TextField
                label={t("messaging.marketing.apiKey", { name: row.name })}
                type="password"
                autoComplete="off"
                value={keys[row.provider] ?? ""}
                onChange={(e) => setKeys({ ...keys, [row.provider]: e.target.value })}
              />
              <Button size="sm" onClick={() => connect.mutate(row.provider)}>
                {t("messaging.marketing.connect")}
              </Button>
            </div>
          )}
        </section>
      ))}
      {sync.data ? (
        <Alert tone="success">
          {t("messaging.marketing.synced", {
            upserted: sync.data.upserted,
            unsubscribed: sync.data.unsubscribed,
          })}{" "}
          {sync.data.opted_out
            ? t("marketingReturn.optedOut", { count: sync.data.opted_out })
            : null}
        </Alert>
      ) : null}
      <Problem error={connect.error ?? sync.error} />
    </div>
  );
}

function Audiences({
  provider,
  current,
  onChosen,
}: {
  provider: string;
  current: string;
  onChosen: () => void;
}) {
  const { t } = useTranslation();
  const audiences = useQuery({
    queryKey: ["marketing-sync", provider, "audiences"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/marketing-sync/{provider}/audiences", {
          params: { path: { provider } },
        }),
      ),
  });
  const choose = useMutation({
    mutationFn: async (audience_id: string) =>
      unwrap(
        await api.PUT("/api/v1/marketing-sync/{provider}/audiences", {
          params: { path: { provider } },
          body: { audience_id },
        }),
      ),
    onSuccess: onChosen,
  });
  return (
    <SelectField
      label={t("messaging.marketing.audience")}
      value={current}
      onChange={(e) => choose.mutate(e.target.value)}
      options={[
        { value: "", label: t("messaging.marketing.chooseAudience") },
        ...(audiences.data ?? []).map((a) => ({
          value: a.id,
          label: t("messaging.marketing.audienceOption", { name: a.name, count: a.members }),
        })),
      ]}
    />
  );
}

/** Settings → Messaging (E13-T11/T12): sender domains, numbers, WhatsApp templates,
 * canned replies and marketing sync. */
export function MessagingSettingsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("domains");
  const tabs: Tab[] = ["domains", "numbers", "whatsapp", "canned", "marketing"];
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("messaging.title")}</h1>
      <Tabs
        label={t("messaging.title")}
        tabs={tabs.map((key) => ({ key, label: t(`messaging.tabs.${key}`) }))}
        value={tab}
        onChange={setTab}
      >
        {tab === "domains" ? <SenderDomains /> : null}
        {tab === "numbers" ? <Numbers /> : null}
        {tab === "whatsapp" ? <WhatsAppTemplates /> : null}
        {tab === "canned" ? <CannedReplies /> : null}
        {tab === "marketing" ? <MarketingSync /> : null}
      </Tabs>
    </section>
  );
}
