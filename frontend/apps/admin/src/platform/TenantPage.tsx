import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FactList,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  RuledTable,
  Spinner,
  TextField,
  UnitField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { api } from "../api";
import { RecordHeader, RecordLayout } from "../components/RecordHeader";
import { TenantHealthCard } from "./HealthPage";
import { orgStatusClass } from "./TenantsPage";

type Detail = components["schemas"]["TenantDetail"];

/** A broken connection is a failure; one to reconnect waits on the customer (margin red). */
const INTEGRATION_CLASS: Record<string, string> = {
  error: "font-medium text-danger",
  needs_reconnect: "font-semibold text-margin",
};

/** Usage limits are lower-case nouns ("tutors"); as fact labels they open with a capital. */
function capitalise(text: string): string {
  return text.charAt(0).toLocaleUpperCase() + text.slice(1);
}
type Member = components["schemas"]["Member"];

/** One organisation as a record: health, members, overrides, errors and activity lead; the
 * subscription, integrations and support actions stand in the side column. */
export function TenantPage({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const detail = useQuery({
    queryKey: ["platform", "tenant", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/platform/tenants/{id}", { params: { path: { id } } })),
  });
  if (detail.isPending) return <Spinner label={t("grid.loading")} />;
  if (!detail.data) return <Alert tone="danger">{t("errors.generic")}</Alert>;
  const d = detail.data;
  const org = d.organisation;
  return (
    <div>
      <RecordHeader
        back={<Link to="/platform">{t("platform.tenants")}</Link>}
        title={org.name}
        description={
          <span className="tabular-nums">
            <span className={orgStatusClass(org.status)}>
              {t(`platform.orgStatus.${org.status}`)}
            </span>
            {[
              org.slug,
              org.country,
              org.default_currency,
              t("platform.createdOn", { date: formatDate(org.created_at, i18n.language) }),
              org.suspension_reason,
            ]
              .filter(Boolean)
              .map((part) => ` · ${part}`)
              .join("")}
          </span>
        }
      />
      <RecordLayout
        main={
          <>
            <TenantHealthCard id={id} />
            <Members detail={d} />
            <Overrides detail={d} />
            {d.recent_errors.length || d.dead_letters ? (
              <RuledPanel
                title={t("platform.errors")}
                aside={
                  d.dead_letters ? (
                    <span className="font-medium text-danger">
                      {t("platform.deadLetterCount", { count: d.dead_letters })}
                    </span>
                  ) : null
                }
                flush
              >
                <PanelRows>
                  {d.recent_errors.map((e, i) => (
                    <PanelRow key={i}>
                      <span className="font-medium">{e.kind}</span>
                      <span className="block text-xs text-muted-foreground tabular-nums">
                        {formatDateTime(e.at, i18n.language)} · {e.origin}
                      </span>
                      <span className="block break-words text-danger">{e.detail}</span>
                    </PanelRow>
                  ))}
                </PanelRows>
              </RuledPanel>
            ) : null}
            <RuledPanel title={t("platform.audit")} flush>
              {d.audit.length ? (
                <PanelRows>
                  {d.audit.map((a) => (
                    <PanelRow key={a.id}>
                      <span className="font-medium">{a.action}</span>
                      <span className="block text-xs text-muted-foreground tabular-nums">
                        {[formatDateTime(a.created_at, i18n.language), a.object_type, a.object_repr]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </PanelRow>
                  ))}
                </PanelRows>
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  {t("designS11.platform.noActivity")}
                </p>
              )}
            </RuledPanel>
          </>
        }
        side={
          <>
            <RuledPanel title={t("platform.subscription")} flush>
              {d.subscription ? (
                <FactList
                  items={[
                    [
                      t("platform.plan"),
                      `${d.subscription.plan} (${t(`platformPlans.intervals.${d.subscription.interval}`, { defaultValue: d.subscription.interval })})`,
                    ],
                    [
                      t("platform.status"),
                      t(`platform.orgStatus.${d.subscription.status}`, {
                        defaultValue: d.subscription.status,
                      }),
                    ],
                    [
                      t("platform.trialEnds"),
                      d.subscription.trial_ends_at
                        ? formatDate(d.subscription.trial_ends_at, i18n.language)
                        : "",
                    ],
                    [
                      t("designS11.platform.stripeCustomer"),
                      d.subscription.stripe_customer_id ? (
                        <span className="font-mono break-all">
                          {d.subscription.stripe_customer_id}
                        </span>
                      ) : (
                        ""
                      ),
                    ],
                  ]}
                />
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  {t("platform.noSubscription")}
                </p>
              )}
              {Object.keys(d.usage).length ? (
                <div className="border-t border-border">
                  <FactList
                    items={Object.entries(d.usage).map(
                      ([key, value]) =>
                        [
                          capitalise(t(`plan.limits.${key}`)),
                          <span key={key} className="tabular-nums">
                            {String(value)}
                          </span>,
                        ] as const,
                    )}
                  />
                </div>
              ) : null}
            </RuledPanel>
            <RuledPanel title={t("gapG6.integrations")} flush>
              {d.addons?.length ? (
                <p className="px-5 pt-3 text-sm">
                  {t("gapG6.addons")}: {d.addons.map((a) => t(`addons.names.${a}`)).join(", ")}
                </p>
              ) : null}
              {d.integrations?.length ? (
                <PanelRows>
                  {d.integrations.map((row) => (
                    <PanelRow key={`${row.provider}-${row.level}-${row.status}`}>
                      <span className="font-medium">{row.provider}</span>
                      <span className="block text-xs text-muted-foreground tabular-nums">
                        <span className={INTEGRATION_CLASS[row.status] ?? ""}>
                          {t(`gapG6.integrationStatus.${row.status}`, { defaultValue: row.status })}
                        </span>{" "}
                        · {t("gapG6.connections", { count: row.connections })}
                        {row.last_sync_at
                          ? ` · ${t("gapG6.lastSync", { date: formatDateTime(row.last_sync_at, i18n.language) })}`
                          : ""}
                      </span>
                      {row.failed_syncs ? (
                        <span className="block text-xs font-medium text-danger">
                          {t("gapG6.failedSyncs", { count: row.failed_syncs })}
                        </span>
                      ) : null}
                    </PanelRow>
                  ))}
                </PanelRows>
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  {t("gapG6.noIntegrations")}
                </p>
              )}
            </RuledPanel>
            <Actions detail={d} />
          </>
        }
      />
    </div>
  );
}

function useTenantAction<T>(id: string, fn: (body: T) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["platform", "tenant", id] }),
  });
}

/** Support actions: one reason for all of them, then one ruled row per action. */
function Actions({ detail }: { detail: Detail }) {
  const { t } = useTranslation();
  const id = detail.organisation.id;
  const path = { params: { path: { id } } };
  const [reason, setReason] = useState("");
  const [days, setDays] = useState("14");
  const [plan, setPlan] = useState("enterprise");
  const [confirmSlug, setConfirmSlug] = useState("");
  const [done, setDone] = useState("");
  const run = useTenantAction(id, async (action: string) => {
    switch (action) {
      case "extend":
        return unwrap(
          await api.POST("/api/v1/platform/tenants/{id}/extend-trial", {
            ...path,
            body: { days: Number(days), reason },
          }),
        );
      case "suspend":
        return unwrap(
          await api.POST("/api/v1/platform/tenants/{id}/suspend", { ...path, body: { reason } }),
        );
      case "unsuspend":
        return unwrap(await api.POST("/api/v1/platform/tenants/{id}/unsuspend", path));
      case "plan":
        return unwrap(
          await api.POST("/api/v1/platform/tenants/{id}/change-plan", {
            ...path,
            body: { plan, interval: "month", note: reason, activate: true },
          }),
        );
      case "verify":
        return unwrap(await api.POST("/api/v1/platform/tenants/{id}/resend-verification", path));
      case "export":
        return unwrap(
          await api.POST("/api/v1/platform/tenants/{id}/export", { ...path, body: { reason } }),
        );
      default:
        return unwrap(
          await api.POST("/api/v1/platform/tenants/{id}/schedule-deletion", {
            ...path,
            body: { reason, confirm_slug: confirmSlug },
          }),
        );
    }
  });
  const act = (action: string) =>
    run.mutate(action, { onSuccess: () => setDone(t(`platform.done.${action}`)) });
  const pending = (action: string) => run.isPending && run.variables === action;
  const suspended = detail.organisation.status === "suspended";
  const row = "border-t border-rule px-5 py-3";
  return (
    <RuledPanel title={t("platform.actions")} flush>
      <div className="px-5 py-4">
        <TextField
          label={t("platform.reason")}
          hint={t("platform.reasonHint")}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </div>
      <div className={`${row} flex flex-wrap items-end gap-2`}>
        <UnitField
          label={t("platform.days")}
          size="sm"
          unit={t("designS11.platform.daysUnit")}
          min={1}
          max={90}
          value={days}
          onChange={(e) => setDays(e.target.value)}
        />
        <Button
          size="sm"
          variant="secondary"
          className="h-9"
          loading={pending("extend")}
          onClick={() => act("extend")}
        >
          {t("platform.extendTrial")}
        </Button>
      </div>
      <div className={`${row} flex flex-wrap items-end gap-2`}>
        <div className="w-40">
          <TextField
            label={t("platform.plan")}
            size="sm"
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
          />
        </div>
        <Button
          size="sm"
          variant="secondary"
          className="h-9"
          loading={pending("plan")}
          onClick={() => act("plan")}
        >
          {t("platform.changePlan")}
        </Button>
      </div>
      <div className={`${row} flex flex-wrap gap-2`}>
        <Button
          size="sm"
          variant="secondary"
          loading={pending(suspended ? "unsuspend" : "suspend")}
          onClick={() => act(suspended ? "unsuspend" : "suspend")}
        >
          {suspended ? t("platform.unsuspend") : t("platform.suspend")}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          loading={pending("verify")}
          onClick={() => act("verify")}
        >
          {t("platform.resendVerification")}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          loading={pending("export")}
          onClick={() => act("export")}
        >
          {t("platform.export")}
        </Button>
      </div>
      <div className={`${row} space-y-2`}>
        <TextField
          label={t("platform.confirmSlug", { slug: detail.organisation.slug })}
          size="sm"
          value={confirmSlug}
          onChange={(e) => setConfirmSlug(e.target.value)}
        />
        <Button
          size="sm"
          variant="danger"
          disabled={confirmSlug !== detail.organisation.slug}
          loading={pending("delete")}
          onClick={() => act("delete")}
        >
          {t("platform.scheduleDeletion")}
        </Button>
      </div>
      {run.error || (done && run.isSuccess) ? (
        <div className="border-t border-rule px-5 py-3">
          {run.error ? <Alert tone="danger">{run.error.message}</Alert> : null}
          {done && run.isSuccess ? <Alert tone="success">{done}</Alert> : null}
        </div>
      ) : null}
    </RuledPanel>
  );
}

function Overrides({ detail }: { detail: Detail }) {
  const { t, i18n } = useTranslation();
  const id = detail.organisation.id;
  const [key, setKey] = useState("");
  const [value, setValue] = useState("on");
  const [reason, setReason] = useState("");
  const [expires, setExpires] = useState("");
  const save = useTenantAction(id, async () => {
    const isFeature = value === "on" || value === "off";
    return unwrap(
      await api.PUT("/api/v1/platform/tenants/{id}/overrides", {
        params: { path: { id } },
        body: {
          key: key as components["schemas"]["OverrideRequestRequest"]["key"],
          enabled: isFeature ? value === "on" : null,
          limit: !isFeature && value !== "unlimited" ? Number(value) : null,
          unlimited: value === "unlimited",
          expires_at: expires ? new Date(expires).toISOString() : null,
          reason,
        },
      }),
    );
  });
  const remove = useTenantAction(id, async (k: string) =>
    unwrap(
      await api.DELETE("/api/v1/platform/tenants/{id}/overrides/{key}", {
        params: { path: { id, key: k } },
      }),
    ),
  );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(undefined);
  };
  return (
    <RuledPanel title={t("platform.overrides")} flush>
      {detail.overrides.length ? (
        <PanelRows>
          {detail.overrides.map((o) => (
            <PanelRow key={o.key} className="flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0">
                <span className="font-mono">{o.key}</span>
                {": "}
                <span className="font-medium">
                  {o.bool_value !== null
                    ? o.bool_value
                      ? t("platform.on")
                      : t("platform.off")
                    : o.unlimited
                      ? t("platform.unlimited")
                      : o.int_value}
                </span>
                <span className="block text-xs text-muted-foreground tabular-nums">
                  {[
                    o.expires_at
                      ? t("platform.until", { date: formatDate(o.expires_at, i18n.language) })
                      : "",
                    o.reason,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="text-muted-foreground"
                onClick={() => remove.mutate(o.key)}
              >
                {t("platform.remove")}
              </Button>
            </PanelRow>
          ))}
        </PanelRows>
      ) : null}
      <form
        onSubmit={submit}
        className={detail.overrides.length ? "border-t border-border" : undefined}
      >
        <div className="grid gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
          <TextField
            label={t("platform.key")}
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <TextField
            label={t("platform.value")}
            hint={t("platform.valueHint")}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <TextField
            label={t("platform.expires")}
            type="date"
            value={expires}
            onChange={(e) => setExpires(e.target.value)}
          />
          <TextField
            label={t("platform.reason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
        {save.error ? (
          <div className="px-5 pb-4">
            <Alert tone="danger">{save.error.message}</Alert>
          </div>
        ) : null}
        <PanelFooter>
          <Button type="submit" size="sm" loading={save.isPending}>
            {t("platform.grant")}
          </Button>
        </PanelFooter>
      </form>
    </RuledPanel>
  );
}

function Members({ detail }: { detail: Detail }) {
  const { t, i18n } = useTranslation();
  const [target, setTarget] = useState<Member | null>(null);
  const [reason, setReason] = useState("");
  const [ticket, setTicket] = useState("");
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/platform/tenants/{id}/support-sessions", {
          params: { path: { id: detail.organisation.id } },
          body: { membership_id: target!.id, reason, ticket, write: false },
        }),
      ),
    onSuccess: (r) => window.open(r.url, "_blank", "noopener"),
  });
  return (
    <RuledPanel
      title={t("platform.members")}
      aside={<span className="text-muted-foreground tabular-nums">{detail.members.length}</span>}
      flush
    >
      <RuledTable
        caption={t("platform.members")}
        columns={[
          { header: t("platform.email") },
          { header: t("platform.lastActivity") },
          { header: t("platform.security") },
          { header: t("platform.actions"), hidden: true },
        ]}
      >
        {detail.members.map((m) => (
          <tr key={m.id}>
            <td className="min-w-48">
              <span className="font-medium [overflow-wrap:anywhere]">{m.email}</span>
              <span className="block text-xs text-muted-foreground">
                {t(`roles.${m.role}`, { defaultValue: m.role })}
              </span>
            </td>
            <td className="whitespace-nowrap tabular-nums">
              {m.last_active_at ? formatDate(m.last_active_at, i18n.language) : "–"}
            </td>
            <td className={m.email_verified ? undefined : "text-muted-foreground"}>
              {m.email_verified ? t("platform.verified") : t("platform.unverified")}
              {m.has_mfa ? ` · ${t("designS11.platform.twoStep")}` : ""}
            </td>
            <td className="py-1.5 text-right align-middle whitespace-nowrap">
              <Button
                size="sm"
                variant="secondary"
                aria-expanded={target?.id === m.id}
                onClick={() => setTarget(m)}
              >
                {t("platform.viewAs")}
              </Button>
            </td>
          </tr>
        ))}
      </RuledTable>
      {target ? (
        <form
          className="border-t border-border"
          aria-label={t("platform.viewAsTitle", { email: target.email })}
          onKeyDown={(e) => {
            if (e.key === "Escape") setTarget(null);
          }}
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate();
          }}
        >
          <div className="space-y-3 px-5 py-4">
            <div>
              <p className="font-medium break-all">
                {t("platform.viewAsTitle", { email: target.email })}
              </p>
              <p className="text-sm text-muted-foreground">{t("platform.viewAsHelp")}</p>
            </div>
            <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
              <TextField
                label={t("platform.reason")}
                autoFocus
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <TextField
                label={t("platform.ticket")}
                value={ticket}
                onChange={(e) => setTicket(e.target.value)}
              />
            </div>
            {start.error ? <Alert tone="danger">{start.error.message}</Alert> : null}
          </div>
          <PanelFooter>
            <Button type="submit" size="sm" loading={start.isPending}>
              {t("platform.openAccount")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-muted-foreground"
              onClick={() => setTarget(null)}
            >
              {t("common.cancel")}
            </Button>
          </PanelFooter>
        </form>
      ) : null}
    </RuledPanel>
  );
}
