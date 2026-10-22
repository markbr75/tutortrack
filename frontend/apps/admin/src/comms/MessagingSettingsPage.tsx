import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  NamePlate,
  PageHeader,
  Panel,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledTable,
  SelectField,
  Spinner,
  Tabs,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, fieldErrors } from "../api";

const PAGE = { params: { query: { page_size: 100 } } };
type Tab = "domains" | "numbers" | "whatsapp" | "canned" | "marketing";

/** An add-something form in a ruled panel: fields in two columns, the submit in the footer. */
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
    <Panel title={title} level={3} flush>
      <form
        aria-label={title}
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          onSubmit();
        }}
      >
        <div className="grid gap-3 px-5 py-4 sm:grid-cols-2">{children}</div>
        <PanelFooter>
          <Button type="submit" size="sm" loading={pending}>
            {submit}
          </Button>
        </PanelFooter>
      </form>
    </Panel>
  );
}

function Problem({ error }: { error: Error | null }) {
  return error ? <Alert tone="danger">{error.message}</Alert> : null;
}

/** One faded-ink line of help under a tab. */
function Help({ children }: { children: ReactNode }) {
  return <p className="max-w-3xl text-sm text-muted-foreground">{children}</p>;
}

/** A flush ruled panel of rows, or one faded-ink sentence when there are none. */
function ListPanel({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string;
  children?: ReactNode;
}) {
  return (
    <Panel title={title} level={3} flush>
      {children ? (
        <PanelRows>{children}</PanelRows>
      ) : (
        <p className="px-5 py-4 text-sm text-muted-foreground">{empty}</p>
      )}
    </Panel>
  );
}

const DOMAIN_TONE: Record<string, string> = {
  pending: "font-semibold text-margin",
  failed: "font-medium text-danger",
  verified: "",
};

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
    <div className="space-y-6">
      <Help>{t("messaging.domains.help")}</Help>
      {rows.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {rows.data?.results.map((row) => (
        <Panel
          key={row.id}
          level={3}
          title={row.from_address}
          description={
            <>
              <span className={DOMAIN_TONE[row.status] ?? ""}>
                {t(`messaging.domains.status.${row.status}`)}
              </span>
              {row.is_default ? ` · ${t("messaging.domains.default")}` : ""}
              {row.last_checked_at ? (
                <span className="tabular-nums">
                  {" · "}
                  {t("messaging.domains.checked", {
                    when: formatDateTime(row.last_checked_at, i18n.language),
                  })}
                </span>
              ) : null}
            </>
          }
          flush
          footer={
            <>
              <Button size="sm" variant="secondary" onClick={() => check.mutate(row.id)}>
                {t("messaging.domains.check")}
              </Button>
              {row.status === "verified" && !row.is_default ? (
                <Button size="sm" variant="secondary" onClick={() => makeDefault.mutate(row.id)}>
                  {t("messaging.domains.makeDefault")}
                </Button>
              ) : null}
            </>
          }
        >
          {row.error ? (
            <div className="px-5 pt-4">
              <Alert tone="warning">{row.error}</Alert>
            </div>
          ) : null}
          <RuledTable
            bare
            caption={t("messaging.domains.records")}
            columns={[
              { label: t("messaging.domains.type") },
              { label: t("messaging.domains.host") },
              { label: t("messaging.domains.value"), className: "min-w-64" },
              { label: t("messaging.domains.verified") },
            ]}
          >
            {row.dns_records.map((r) => (
              <tr key={`${r.purpose}-${r.host}`}>
                <td className="font-medium">{r.record_type}</td>
                <td className="break-all">{r.host}</td>
                <td className="text-xs break-all">{r.value}</td>
                <td className="whitespace-nowrap">
                  {["spf", "dmarc"].includes(r.purpose) ? (
                    <span className="text-muted-foreground">
                      {t("messaging.domains.recommended")}
                    </span>
                  ) : r.verified ? (
                    t("messaging.yes")
                  ) : (
                    <span className="font-semibold text-margin">{t("messaging.no")}</span>
                  )}
                </td>
              </tr>
            ))}
          </RuledTable>
        </Panel>
      ))}
      <Problem error={check.error ?? makeDefault.error} />
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
  const list = rows.data?.results ?? [];
  return (
    <div className="space-y-6">
      <Help>{t("messaging.numbers.help")}</Help>
      {rows.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : (
        <ListPanel title={t("messaging.tabs.numbers")} empty={t("designS8.comms.noNumbers")}>
          {list.length
            ? list.map((row) => (
                <PanelRow key={row.id}>
                  <NamePlate
                    name={<span className="tabular-nums">{row.number}</span>}
                    context={[
                      t(`comms.channel.${row.channel}`),
                      row.label,
                      row.is_default ? t("messaging.domains.default") : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                    aside={
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-muted-foreground"
                        aria-label={t("designS8.comms.removeNamed", { name: row.number })}
                        onClick={() => remove.mutate(row.id)}
                      >
                        {t("messaging.remove")}
                      </Button>
                    }
                  />
                </PanelRow>
              ))
            : null}
        </ListPanel>
      )}
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
          className="tabular-nums"
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
      <Problem error={remove.error} />
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
  const usedFor = (key: string) =>
    key
      ? (types.data?.find((s) => s.key === key)?.label ?? key)
      : t("messaging.whatsapp.broadcastsOnly");
  const list = rows.data?.results ?? [];
  return (
    <div className="space-y-6">
      <Help>{t("messaging.whatsapp.help")}</Help>
      {rows.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : (
        <ListPanel title={t("messaging.tabs.whatsapp")} empty={t("designS8.comms.noTemplates")}>
          {list.length
            ? list.map((row) => (
                <PanelRow key={row.id}>
                  <NamePlate
                    name={row.name}
                    context={
                      <>
                        <span
                          className={
                            row.status === "pending"
                              ? "font-semibold text-margin"
                              : row.status === "rejected"
                                ? "font-medium text-danger"
                                : undefined
                          }
                        >
                          {t(`messaging.whatsapp.status.${row.status}`)}
                        </span>
                        {" · "}
                        {usedFor(row.type_key ?? "")}
                      </>
                    }
                  />
                  <p className="mt-1 whitespace-pre-wrap">{row.body}</p>
                </PanelRow>
              ))
            : null}
        </ListPanel>
      )}
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
  const list = rows.data?.results ?? [];
  return (
    <div className="space-y-6">
      {rows.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : (
        <ListPanel title={t("messaging.tabs.canned")} empty={t("designS8.comms.noCanned")}>
          {list.length
            ? list.map((row) => (
                <PanelRow key={row.id}>
                  <NamePlate
                    name={row.title}
                    context={row.body}
                    aside={
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-muted-foreground"
                        aria-label={t("designS8.comms.removeNamed", { name: row.title })}
                        onClick={() => remove.mutate(row.id)}
                      >
                        {t("messaging.remove")}
                      </Button>
                    }
                  />
                </PanelRow>
              ))
            : null}
        </ListPanel>
      )}
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
    <div className="space-y-6">
      <Help>{t("messaging.marketing.help")}</Help>
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
      {rows.data?.map((row) =>
        row.connection ? (
          <Panel
            key={row.provider}
            level={3}
            title={row.name}
            aside={<span>{row.account_name || t("messaging.marketing.connected")}</span>}
            description={
              row.last_sync_at ? (
                <span className="tabular-nums">
                  {t("messaging.marketing.lastSync", {
                    when: formatDateTime(row.last_sync_at, i18n.language),
                  })}
                </span>
              ) : undefined
            }
            footer={
              <Button
                size="sm"
                variant="secondary"
                disabled={!row.audience_id}
                loading={sync.isPending && sync.variables === row.provider}
                onClick={() => sync.mutate(row.provider)}
              >
                {t("messaging.marketing.syncNow")}
              </Button>
            }
            bodyClassName="space-y-4"
          >
            <div className="max-w-sm">
              <Audiences provider={row.provider} current={row.audience_id} onChosen={refresh} />
            </div>
            {row.error ? <Alert tone="warning">{row.error}</Alert> : null}
            {row.webhook_url ? (
              <TextField
                label={t("marketingReturn.webhook", { name: row.name })}
                hint={t("marketingReturn.webhookHint", { name: row.name })}
                readOnly
                className="bg-background"
                value={row.webhook_url}
                onFocus={(e) => e.target.select()}
              />
            ) : null}
          </Panel>
        ) : (
          <Panel
            key={row.provider}
            level={3}
            title={row.name}
            aside={
              <span className="text-muted-foreground">{t("designS8.comms.notConnected")}</span>
            }
            flush
          >
            <form
              aria-label={row.name}
              onSubmit={(e) => {
                e.preventDefault();
                connect.mutate(row.provider);
              }}
            >
              <div className="max-w-sm px-5 py-4">
                <TextField
                  label={t("messaging.marketing.apiKey", { name: row.name })}
                  type="password"
                  autoComplete="off"
                  value={keys[row.provider] ?? ""}
                  onChange={(e) => setKeys({ ...keys, [row.provider]: e.target.value })}
                />
              </div>
              <PanelFooter>
                <Button
                  type="submit"
                  size="sm"
                  loading={connect.isPending && connect.variables === row.provider}
                >
                  {t("messaging.marketing.connect")}
                </Button>
              </PanelFooter>
            </form>
          </Panel>
        ),
      )}
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
    <section className="max-w-4xl">
      <PageHeader title={t("messaging.title")} />
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
