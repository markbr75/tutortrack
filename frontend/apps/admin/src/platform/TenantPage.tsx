import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { api } from "../api";

type Detail = components["schemas"]["TenantDetail"];
type Member = components["schemas"]["Member"];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 rounded-md border border-border p-4">
      <h2 className="font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** One organisation: subscription, usage, members, errors, audit and support actions. */
export function TenantPage({ id }: { id: string }) {
  const { t } = useTranslation();
  const detail = useQuery({
    queryKey: ["platform", "tenant", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/platform/tenants/{id}", { params: { path: { id } } })),
  });
  if (detail.isPending) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (!detail.data) return <Alert tone="danger">{t("errors.generic")}</Alert>;
  const d = detail.data;
  const org = d.organisation;
  return (
    <div className="max-w-5xl space-y-4">
      <h1 className="text-2xl font-semibold">
        {org.name} <span className="text-base text-muted-foreground">{org.slug}</span>
      </h1>
      <p className="text-sm">
        {t(`platform.orgStatus.${org.status}`)} · {org.country} · {org.default_currency} ·{" "}
        {t("platform.createdOn", { date: formatDate(org.created_at) })}
        {org.suspension_reason ? ` · ${org.suspension_reason}` : ""}
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title={t("platform.subscription")}>
          {d.subscription ? (
            <dl className="grid grid-cols-2 gap-1 text-sm">
              <dt>{t("platform.plan")}</dt>
              <dd>
                {d.subscription.plan} ({d.subscription.interval})
              </dd>
              <dt>{t("platform.status")}</dt>
              <dd>{d.subscription.status}</dd>
              {d.subscription.trial_ends_at ? (
                <>
                  <dt>{t("platform.trialEnds")}</dt>
                  <dd>{formatDate(d.subscription.trial_ends_at)}</dd>
                </>
              ) : null}
              <dt>Stripe</dt>
              <dd className="break-all">{d.subscription.stripe_customer_id || "–"}</dd>
            </dl>
          ) : (
            <p className="text-sm">{t("platform.noSubscription")}</p>
          )}
          <ul className="text-sm">
            {Object.entries(d.usage).map(([key, value]) => (
              <li key={key}>
                {t(`plan.limits.${key}`)}: {value}
              </li>
            ))}
          </ul>
        </Section>
        <Actions detail={d} />
      </div>
      <Overrides detail={d} />
      <Members detail={d} />
      {d.recent_errors.length || d.dead_letters ? (
        <Section title={t("platform.errors")}>
          {d.dead_letters ? (
            <p className="text-sm">{t("platform.deadLetterCount", { count: d.dead_letters })}</p>
          ) : null}
          <ul className="space-y-1 text-sm">
            {d.recent_errors.map((e, i) => (
              <li key={i}>
                {formatDateTime(e.at)} · {e.origin} · {e.kind}: {e.detail}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      <Section title={t("platform.audit")}>
        <ul className="space-y-1 text-sm">
          {d.audit.map((a) => (
            <li key={a.id}>
              {formatDateTime(a.created_at)} · {a.action} · {a.object_type} {a.object_repr}
            </li>
          ))}
        </ul>
      </Section>
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
  const suspended = detail.organisation.status === "suspended";
  return (
    <Section title={t("platform.actions")}>
      <TextField
        label={t("platform.reason")}
        hint={t("platform.reasonHint")}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div className="flex flex-wrap items-end gap-2">
        <TextField
          label={t("platform.days")}
          type="number"
          min={1}
          max={90}
          value={days}
          onChange={(e) => setDays(e.target.value)}
          className="w-24"
        />
        <Button size="sm" variant="secondary" onClick={() => act("extend")}>
          {t("platform.extendTrial")}
        </Button>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <TextField
          label={t("platform.plan")}
          value={plan}
          onChange={(e) => setPlan(e.target.value)}
          className="w-40"
        />
        <Button size="sm" variant="secondary" onClick={() => act("plan")}>
          {t("platform.changePlan")}
        </Button>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => act(suspended ? "unsuspend" : "suspend")}
        >
          {suspended ? t("platform.unsuspend") : t("platform.suspend")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => act("verify")}>
          {t("platform.resendVerification")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => act("export")}>
          {t("platform.export")}
        </Button>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <TextField
          label={t("platform.confirmSlug", { slug: detail.organisation.slug })}
          value={confirmSlug}
          onChange={(e) => setConfirmSlug(e.target.value)}
        />
        <Button size="sm" variant="danger" onClick={() => act("delete")}>
          {t("platform.scheduleDeletion")}
        </Button>
      </div>
      {run.error ? <Alert tone="danger">{run.error.message}</Alert> : null}
      {done && run.isSuccess ? <Alert tone="success">{done}</Alert> : null}
    </Section>
  );
}

function Overrides({ detail }: { detail: Detail }) {
  const { t } = useTranslation();
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
    <Section title={t("platform.overrides")}>
      <ul className="text-sm">
        {detail.overrides.map((o) => (
          <li key={o.key} className="flex items-center justify-between gap-2 py-1">
            <span>
              {o.key}:{" "}
              {o.bool_value !== null
                ? String(o.bool_value)
                : o.unlimited
                  ? t("platform.unlimited")
                  : o.int_value}
              {o.expires_at ? ` · ${t("platform.until", { date: formatDate(o.expires_at) })}` : ""}
              {" · "}
              {o.reason}
            </span>
            <Button size="sm" variant="ghost" onClick={() => remove.mutate(o.key)}>
              {t("platform.remove")}
            </Button>
          </li>
        ))}
      </ul>
      <form className="flex flex-wrap items-end gap-2" onSubmit={submit}>
        <TextField label={t("platform.key")} value={key} onChange={(e) => setKey(e.target.value)} />
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
        <Button type="submit" size="sm" loading={save.isPending}>
          {t("platform.grant")}
        </Button>
      </form>
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </Section>
  );
}

function Members({ detail }: { detail: Detail }) {
  const { t } = useTranslation();
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
    <Section title={t("platform.members")}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col">{t("platform.email")}</th>
              <th scope="col">{t("platform.role")}</th>
              <th scope="col">{t("platform.lastActivity")}</th>
              <th scope="col">{t("platform.security")}</th>
              <th scope="col">
                <span className="sr-only">{t("platform.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {detail.members.map((m) => (
              <tr key={m.id} className="border-t border-border">
                <td>{m.email}</td>
                <td>{m.role}</td>
                <td>{m.last_active_at ? formatDate(m.last_active_at) : "–"}</td>
                <td>
                  {m.email_verified ? t("platform.verified") : t("platform.unverified")}
                  {m.has_mfa ? " · 2FA" : ""}
                </td>
                <td>
                  <Button size="sm" variant="ghost" onClick={() => setTarget(m)}>
                    {t("platform.viewAs")}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {target ? (
        <form
          className="space-y-2"
          aria-label={t("platform.viewAsTitle", { email: target.email })}
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate();
          }}
        >
          <p className="text-sm font-medium">
            {t("platform.viewAsTitle", { email: target.email })}
          </p>
          <p className="text-sm text-muted-foreground">{t("platform.viewAsHelp")}</p>
          <TextField
            label={t("platform.reason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <TextField
            label={t("platform.ticket")}
            value={ticket}
            onChange={(e) => setTicket(e.target.value)}
          />
          <div className="flex gap-2">
            <Button type="submit" size="sm" loading={start.isPending}>
              {t("platform.openAccount")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setTarget(null)}>
              {t("common.cancel")}
            </Button>
          </div>
          {start.error ? <Alert tone="danger">{start.error.message}</Alert> : null}
        </form>
      ) : null}
    </Section>
  );
}
