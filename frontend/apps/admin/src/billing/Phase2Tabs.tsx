import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { useCursorList } from "../lists";
import { useClientOptions } from "../payments/clientOptions";

type Package = components["schemas"]["PackagePurchase"];
type Plan = components["schemas"]["BillingPlan"];
type Money = { amount: string; currency: string };

function useMoney() {
  const { i18n } = useTranslation();
  return (value: Money) => formatMoney(value, i18n.language);
}

function units(value: string): string {
  return String(Number(value));
}

// --- packages (E10-T12) -------------------------------------------------------------------

function SellPackage({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const money = useMoney();
  const clients = useClientOptions();
  const templates = useQuery({
    queryKey: ["package-templates", "active"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/packages", { params: { query: { active: true } } }))
        .results,
  });
  const [client, setClient] = useState("");
  const [template, setTemplate] = useState("");
  const sell = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/packages", { body: { client, template } })),
    onSuccess: onDone,
  });
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      aria-label={t("packages.sell")}
      onSubmit={(e) => {
        e.preventDefault();
        sell.mutate();
      }}
    >
      <SelectField
        label={t("billing.client")}
        value={client}
        onChange={(e) => setClient(e.target.value)}
        options={[{ value: "", label: t("bank.chooseClient") }, ...(clients.data ?? [])]}
      />
      <SelectField
        label={t("packages.template")}
        value={template}
        onChange={(e) => setTemplate(e.target.value)}
        options={[
          { value: "", label: t("packages.chooseTemplate") },
          ...(templates.data ?? []).map((p) => ({
            value: p.id,
            label: `${p.name} · ${money(p.price)}`,
          })),
        ]}
      />
      <Button type="submit" size="sm" disabled={!client || !template || sell.isPending}>
        {t("packages.sell")}
      </Button>
      {sell.data ? (
        <Alert tone="success">
          {t("packages.sold", { invoice: sell.data.invoice_number || "—" })}
        </Alert>
      ) : null}
      <ErrorList error={sell.error} />
    </form>
  );
}

function PackageRow({ row, onChange }: { row: Package; onChange: () => void }) {
  const { t, i18n } = useTranslation();
  const canManage = usePermission("billing.package.manage");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const cancel = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/packages/{id}/cancel", {
          params: { path: { id: row.id } },
          body: { reason },
        }),
      ),
    onSuccess: onChange,
  });
  const extend = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/packages/{id}/extend", {
          params: { path: { id: row.id } },
          body: { until: new Date(`${until}T23:59:00`).toISOString() },
        }),
      ),
    onSuccess: onChange,
  });
  const live = row.status === "active" || row.status === "pending";
  return (
    <li className="space-y-2 p-3">
      <div className="flex flex-wrap justify-between gap-2">
        <span>
          <span className="font-medium">{row.name}</span> · {row.client_name}
          {row.student_name ? ` · ${row.student_name}` : ""}
        </span>
        <span>
          {t(`packages.left.${row.quantity_type}`, {
            left: units(row.units_remaining),
            total: units(row.units_total),
          })}{" "}
          · {t(`packages.status.${row.status}`)}
          {row.expires_at
            ? ` · ${t("packages.expires", { date: formatDate(row.expires_at, i18n.language) })}`
            : ""}
        </span>
      </div>
      {canManage && live ? (
        <div className="flex flex-wrap items-end gap-2">
          <TextField
            type="date"
            label={t("packages.extendTo")}
            value={until}
            onChange={(e) => setUntil(e.target.value)}
          />
          <Button size="sm" variant="secondary" disabled={!until} onClick={() => extend.mutate()}>
            {t("packages.extend")}
          </Button>
          <TextField
            label={t("packages.cancelReason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <Button size="sm" variant="ghost" disabled={!reason} onClick={() => cancel.mutate()}>
            {t("packages.cancel")}
          </Button>
        </div>
      ) : null}
      <ErrorList error={cancel.error ?? extend.error} />
    </li>
  );
}

/** Billing → Packages: packages sold to clients, what is left, and selling one (FR-10-7). */
export function PackagesTab({ clientId }: { clientId?: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canSell = usePermission("billing.package.sell");
  const list = useCursorList(["packages", clientId ?? "all"], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/packages", {
        params: { query: { cursor, ...(clientId ? { client: clientId } : {}) } },
      }),
    ),
  );
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["packages"] });
  return (
    <div className="space-y-4">
      {canSell && !clientId ? <SellPackage onDone={refresh} /> : null}
      {list.query.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : list.rows.length ? (
        <ul className="divide-y divide-border rounded-md border border-border text-sm">
          {list.rows.map((row) => (
            <PackageRow key={row.id} row={row} onChange={refresh} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{t("grid.empty")}</p>
      )}
    </div>
  );
}

// --- recurring fees (E10-T13) -------------------------------------------------------------

function NewPlan({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const clients = useClientOptions();
  const [form, setForm] = useState({
    client: "",
    description: "",
    amount: "",
    currency: "GBP",
    interval: "monthly" as "weekly" | "monthly" | "termly",
    start_date: "",
    prorate: true,
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/billing-plans", {
          body: {
            client: form.client,
            description: form.description,
            amount: { amount: form.amount, currency: form.currency },
            interval: form.interval,
            start_date: form.start_date,
            prorate: form.prorate,
            attendance_independent: true,
          },
        }),
      ),
    onSuccess: onDone,
  });
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      aria-label={t("plans.new")}
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <SelectField
        label={t("billing.client")}
        value={form.client}
        onChange={(e) => setForm({ ...form, client: e.target.value })}
        options={[{ value: "", label: t("bank.chooseClient") }, ...(clients.data ?? [])]}
      />
      <TextField
        label={t("billing.description")}
        value={form.description}
        onChange={(e) => setForm({ ...form, description: e.target.value })}
      />
      <TextField
        label={t("billing.amount")}
        type="number"
        step="0.01"
        min={0}
        value={form.amount}
        onChange={(e) => setForm({ ...form, amount: e.target.value })}
      />
      <SelectField
        label={t("plans.interval")}
        value={form.interval}
        onChange={(e) => setForm({ ...form, interval: e.target.value as typeof form.interval })}
        options={(["weekly", "monthly", "termly"] as const).map((v) => ({
          value: v,
          label: t(`plans.intervals.${v}`),
        }))}
      />
      <TextField
        label={t("plans.start")}
        type="date"
        value={form.start_date}
        onChange={(e) => setForm({ ...form, start_date: e.target.value })}
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={form.prorate}
          onChange={(e) => setForm({ ...form, prorate: e.target.checked })}
        />
        {t("plans.prorate")}
      </label>
      <Button
        type="submit"
        size="sm"
        disabled={!form.client || !form.amount || !form.start_date || create.isPending}
      >
        {t("plans.create")}
      </Button>
      <ErrorList error={create.error} />
    </form>
  );
}

function PlanRow({ plan, onChange }: { plan: Plan; onChange: () => void }) {
  const { t, i18n } = useTranslation();
  const money = useMoney();
  const canManage = usePermission("billing.plan.manage");
  const change = useMutation({
    mutationFn: async (status: "active" | "paused" | "ended") =>
      unwrap(
        await api.POST("/api/v1/billing-plans/{id}/status", {
          params: { path: { id: plan.id } },
          body: { status },
        }),
      ),
    onSuccess: onChange,
  });
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 p-3">
      <span>
        <span className="font-medium">{plan.description}</span> · {plan.client_name} ·{" "}
        {money(plan.amount)} {t(`plans.intervals.${plan.interval}`)} ·{" "}
        {t("plans.from", { date: formatDate(plan.start_date, i18n.language) })} ·{" "}
        {t(`plans.status.${plan.status}`)}
      </span>
      {canManage && plan.status !== "ended" ? (
        <span className="flex gap-2">
          {plan.status === "active" ? (
            <Button size="sm" variant="secondary" onClick={() => change.mutate("paused")}>
              {t("plans.pause")}
            </Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={() => change.mutate("active")}>
              {t("plans.resume")}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => change.mutate("ended")}>
            {t("plans.end")}
          </Button>
        </span>
      ) : null}
      <ErrorList error={change.error} />
    </li>
  );
}

/** Billing → Recurring fees (FR-10-8). */
export function PlansTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("billing.plan.manage");
  const list = useCursorList(["billing-plans"], async (cursor) =>
    unwrap(await api.GET("/api/v1/billing-plans", { params: { query: { cursor } } })),
  );
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["billing-plans"] });
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("plans.help")}</p>
      {canManage ? <NewPlan onDone={refresh} /> : null}
      {list.query.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : list.rows.length ? (
        <ul className="divide-y divide-border rounded-md border border-border text-sm">
          {list.rows.map((plan) => (
            <PlanRow key={plan.id} plan={plan} onChange={refresh} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{t("grid.empty")}</p>
      )}
    </div>
  );
}

// --- late fees and collections (E10-T14) --------------------------------------------------

type Rule = components["schemas"]["LateFeeRule"];

function RuleForm({ rule, onDone }: { rule: Rule | undefined; onDone: () => void }) {
  const { t } = useTranslation();
  const [form, setForm] = useState({
    kind: rule?.kind ?? "fixed",
    amount: rule?.amount ?? "10.00",
    percent: rule?.percent ?? "0.00",
    days_overdue: rule?.days_overdue ?? 14,
    recurrence: rule?.recurrence ?? "once",
    max_applications: rule?.max_applications ?? 1,
    mode: rule?.mode ?? "next_invoice",
    active: rule?.active ?? true,
  });
  const save = useMutation({
    mutationFn: async () =>
      rule
        ? unwrap(
            await api.PATCH("/api/v1/billing/late-fee-rules/{id}", {
              params: { path: { id: rule.id } },
              body: form,
            }),
          )
        : unwrap(await api.POST("/api/v1/billing/late-fee-rules", { body: form as never })),
    onSuccess: onDone,
  });
  return (
    <form
      className="grid gap-3 sm:grid-cols-2"
      aria-label={t("lateFees.rule")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <SelectField
        label={t("lateFees.kind")}
        value={form.kind}
        onChange={(e) => setForm({ ...form, kind: e.target.value as "fixed" | "percent" })}
        options={[
          { value: "fixed", label: t("lateFees.kinds.fixed") },
          { value: "percent", label: t("lateFees.kinds.percent") },
        ]}
      />
      {form.kind === "fixed" ? (
        <TextField
          label={t("lateFees.amount")}
          type="number"
          step="0.01"
          value={form.amount}
          onChange={(e) => setForm({ ...form, amount: e.target.value })}
        />
      ) : (
        <TextField
          label={t("lateFees.percent")}
          type="number"
          step="0.01"
          value={form.percent}
          onChange={(e) => setForm({ ...form, percent: e.target.value })}
        />
      )}
      <TextField
        label={t("lateFees.daysOverdue")}
        type="number"
        min={0}
        value={form.days_overdue}
        onChange={(e) => setForm({ ...form, days_overdue: Number(e.target.value) })}
      />
      <SelectField
        label={t("lateFees.recurrence")}
        value={form.recurrence}
        onChange={(e) => setForm({ ...form, recurrence: e.target.value as "once" | "monthly" })}
        options={[
          { value: "once", label: t("lateFees.recurrences.once") },
          { value: "monthly", label: t("lateFees.recurrences.monthly") },
        ]}
      />
      {form.recurrence === "monthly" ? (
        <TextField
          label={t("lateFees.maxApplications")}
          type="number"
          min={1}
          value={form.max_applications}
          onChange={(e) => setForm({ ...form, max_applications: Number(e.target.value) })}
        />
      ) : null}
      <SelectField
        label={t("lateFees.mode")}
        value={form.mode}
        onChange={(e) => setForm({ ...form, mode: e.target.value as "next_invoice" | "immediate" })}
        options={[
          { value: "next_invoice", label: t("lateFees.modes.next_invoice") },
          { value: "immediate", label: t("lateFees.modes.immediate") },
        ]}
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={form.active}
          onChange={(e) => setForm({ ...form, active: e.target.checked })}
        />
        {t("lateFees.active")}
      </label>
      <div>
        <Button type="submit" size="sm" disabled={save.isPending}>
          {t("lateFees.save")}
        </Button>
      </div>
      {save.isSuccess ? <Alert tone="success">{t("lateFees.saved")}</Alert> : null}
      <ErrorList error={save.error} />
    </form>
  );
}

/** Billing → Late fees: the late fee rule and clients in collections (FR-10-10). */
export function LateFeesTab() {
  const { t, i18n } = useTranslation();
  const money = useMoney();
  const queryClient = useQueryClient();
  const canManage = usePermission("billing.late_fee.manage");
  const canClose = usePermission("billing.collections.manage");
  const rules = useQuery({
    queryKey: ["late-fee-rules"],
    queryFn: async () => unwrap(await api.GET("/api/v1/billing/late-fee-rules")),
  });
  const cases = useCursorList(["collections"], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/billing/collections", {
        params: { query: { status: ["open"], cursor } },
      }),
    ),
  );
  const close = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/billing/collections/{id}/close", {
          params: { path: { id } },
          body: { reason: "" },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["collections"] }),
  });
  const rule = rules.data?.find((r) => r.active && !r.branch);
  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t("lateFees.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("lateFees.help")}</p>
        {rules.isPending ? (
          <Spinner className="size-5" label={t("grid.loading")} />
        ) : canManage ? (
          <RuleForm
            key={rule?.id ?? "new"}
            rule={rule}
            onDone={() => void queryClient.invalidateQueries({ queryKey: ["late-fee-rules"] })}
          />
        ) : null}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t("lateFees.collections")}</h2>
        {cases.query.isPending ? (
          <Spinner className="size-5" label={t("grid.loading")} />
        ) : cases.rows.length ? (
          <ul className="divide-y divide-border rounded-md border border-border text-sm">
            {cases.rows.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                <span>
                  {c.client_name} · {c.invoice_number} · {money(c.balance_due)} ·{" "}
                  {t(`lateFees.blocks.${c.block}`)} · {formatDate(c.opened_at, i18n.language)}
                </span>
                {canClose ? (
                  <Button size="sm" variant="ghost" onClick={() => close.mutate(c.id)}>
                    {t("lateFees.closeCase")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{t("lateFees.noneInCollections")}</p>
        )}
        <ErrorList error={close.error} />
      </section>
    </div>
  );
}

// --- split billing (E10-T15) --------------------------------------------------------------

/** Billing → Split billing: share a job's charges between paying clients (FR-10-12). */
export function SplitsTab() {
  const { t } = useTranslation();
  const clients = useClientOptions();
  const jobs = useQuery({
    queryKey: ["job-options"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/jobs", { params: { query: { page_size: 200 } } })).results.map(
        (j) => ({ value: j.id, label: `${j.reference} ${j.name}` }),
      ),
  });
  const [job, setJob] = useState("");
  const [shares, setShares] = useState([
    { client: "", percent: "50" },
    { client: "", percent: "50" },
  ]);
  const current = useQuery({
    queryKey: ["billing-split", job],
    enabled: Boolean(job),
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/billing/splits", { params: { query: { job } } })),
  });
  const save = useMutation({
    mutationFn: async (rows: { client: string; percent: string }[]) =>
      unwrap(await api.POST("/api/v1/billing/splits", { body: { job, shares: rows } })),
    onSuccess: () => void current.refetch(),
  });
  const total = shares.reduce((sum, s) => sum + Number(s.percent || 0), 0);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("splits.help")}</p>
      <SelectField
        label={t("splits.job")}
        value={job}
        onChange={(e) => setJob(e.target.value)}
        options={[{ value: "", label: t("splits.chooseJob") }, ...(jobs.data ?? [])]}
      />
      {job && current.data ? (
        <p className="text-sm">
          {current.data.shares.length
            ? current.data.shares.map((s) => `${s.client_name} ${Number(s.percent)}%`).join(", ")
            : t("splits.none")}
        </p>
      ) : null}
      {job ? (
        <form
          className="space-y-2"
          aria-label={t("splits.edit")}
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(shares);
          }}
        >
          {shares.map((share, i) => (
            <div key={i} className="flex flex-wrap gap-2">
              <SelectField
                label={t("bank.client", { n: i + 1 })}
                value={share.client}
                onChange={(e) =>
                  setShares(shares.map((s, j) => (j === i ? { ...s, client: e.target.value } : s)))
                }
                options={[{ value: "", label: t("bank.chooseClient") }, ...(clients.data ?? [])]}
              />
              <TextField
                label={t("splits.percent", { n: i + 1 })}
                type="number"
                step="0.01"
                value={share.percent}
                onChange={(e) =>
                  setShares(shares.map((s, j) => (j === i ? { ...s, percent: e.target.value } : s)))
                }
              />
            </div>
          ))}
          <p className="text-sm" aria-live="polite">
            {t("splits.total", { total })}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setShares([...shares, { client: "", percent: "" }])}
            >
              {t("bank.addPart")}
            </Button>
            <Button type="submit" size="sm" disabled={total !== 100 || save.isPending}>
              {t("splits.save")}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => save.mutate([])}>
              {t("splits.remove")}
            </Button>
          </div>
          <ErrorList error={save.error} />
        </form>
      ) : null}
    </div>
  );
}
