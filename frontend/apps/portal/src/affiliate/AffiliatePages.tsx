import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { FileText, House, Landmark, Users } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { api, problemStatus } from "../api";
import { BrandMark, PoweredBy } from "../branding";
import { PortalFrame } from "../layout/PortalFrame";
import { CopyLink } from "../pages/ReferralsPage";

function useAffiliate() {
  return useQuery({
    queryKey: ["portal", "affiliate"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/affiliate")),
  });
}

function Th({ children }: { children: ReactNode }) {
  return (
    <th scope="col" className="px-2 py-1 text-left">
      {children}
    </th>
  );
}

function Td({ children }: { children: ReactNode }) {
  return <td className="border-t border-border px-2 py-1 align-top">{children}</td>;
}

/** The partner (affiliate) portal shell (FR-25-3). */
export function AffiliateShell() {
  const { t } = useTranslation();
  const me = useAffiliate();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (!location.pathname.startsWith("/affiliate")) void navigate({ to: "/affiliate" });
  }, [location.pathname, navigate]);
  const logout = useMutation({
    mutationFn: async () => api.POST("/api/v1/auth/logout"),
    onSuccess: () => window.location.assign("/portal/"),
  });
  if (me.isPending) return <Spinner className="p-6" label={t("grid.loading")} />;
  if (!me.data) {
    return (
      <main className="mx-auto max-w-sm p-6">
        <p>
          {t(problemStatus(me.error) === 403 ? "referrals.partner.noAccess" : "errors.generic")}
        </p>
      </main>
    );
  }
  const nav = [
    { to: "/affiliate", label: t("referrals.partner.nav.home"), icon: House },
    { to: "/affiliate/clients", label: t("referrals.partner.nav.clients"), icon: Users },
    { to: "/affiliate/statements", label: t("referrals.partner.nav.statements"), icon: FileText },
    { to: "/affiliate/payout", label: t("referrals.partner.nav.payout"), icon: Landmark },
  ];
  return (
    <PortalFrame
      brand={<BrandMark fallback={me.data.organisation} />}
      navLabel={t("referrals.partner.menu")}
      items={nav}
      primary={nav.map((item) => item.to)}
      root="/affiliate"
      person={me.data.name}
      onSignOut={() => logout.mutate()}
      footer={<PoweredBy />}
    >
      <Outlet />
    </PortalFrame>
  );
}

export function AffiliateHomePage() {
  const { t, i18n } = useTranslation();
  const me = useAffiliate();
  if (!me.data) return null;
  const s = me.data.summary;
  return (
    <section className="space-y-8" aria-labelledby="partner-title">
      <h1 id="partner-title" className="text-xl font-semibold">
        {t("referrals.partner.welcome", { name: me.data.name })}
      </h1>
      <div className="space-y-3">
        {/* One ruled line of figures, not tiles. */}
        <dl className="grid grid-cols-3 border-y border-border">
          {(
            [
              ["clicks", s.clicks],
              ["referred", s.referred],
              ["converted", s.converted],
            ] as const
          ).map(([key, value]) => (
            <div key={key} className="border-l border-rule py-3 pl-4 first:border-l-0 first:pl-0">
              <dt className="text-sm text-muted-foreground">{t(`referrals.partner.${key}`)}</dt>
              <dd className="text-xl font-semibold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        {s.totals.map((total) => (
          <p key={total.currency} className="text-sm">
            {t("referrals.partner.totals", {
              earned: formatMoney(total.earned, i18n.language),
              unpaid: formatMoney(total.unpaid, i18n.language),
            })}
          </p>
        ))}
      </div>
      <div className="space-y-3">
        <h2 className="text-base font-semibold">{t("referrals.partner.links")}</h2>
        <div className="space-y-4 rounded-xl border border-border bg-surface p-4">
          {me.data.links.map((link) => (
            <CopyLink
              key={link.code}
              label={`${link.name || link.code} · ${t("referrals.partner.clickCount", { count: link.clicks })}`}
              url={link.url}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

export function AffiliateClientsPage() {
  const { t, i18n } = useTranslation();
  const clients = useQuery({
    queryKey: ["portal", "affiliate", "clients"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/affiliate/clients")),
  });
  if (!clients.data) return <Spinner label={t("grid.loading")} />;
  if (!clients.data.length) return <p>{t("referrals.partner.noClients")}</p>;
  return (
    <table className="w-full text-sm">
      <caption className="mb-2 text-left font-semibold">
        {t("referrals.partner.nav.clients")}
      </caption>
      <thead>
        <tr>
          <Th>{t("referrals.partner.client")}</Th>
          <Th>{t("referrals.partner.joined")}</Th>
          <Th>{t("referrals.partner.firstPayment")}</Th>
          <Th>{t("referrals.partner.commission")}</Th>
        </tr>
      </thead>
      <tbody>
        {clients.data.map((c) => (
          <tr key={c.id}>
            <Td>{c.name}</Td>
            <Td>{formatDate(c.attributed_at, i18n.language)}</Td>
            <Td>{c.converted_at ? formatDate(c.converted_at, i18n.language) : "—"}</Td>
            <Td>{c.commission ? formatMoney(c.commission, i18n.language) : "—"}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AffiliateStatementsPage() {
  const { t, i18n } = useTranslation();
  const statements = useQuery({
    queryKey: ["portal", "affiliate", "statements"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/affiliate/statements")),
  });
  if (!statements.data) return <Spinner label={t("grid.loading")} />;
  if (!statements.data.length) return <p>{t("referrals.partner.noStatements")}</p>;
  return (
    <div className="space-y-6">
      {statements.data.map((st) => (
        <section key={st.id} aria-labelledby={`st-${st.id}`} className="space-y-2">
          <h2 id={`st-${st.id}`} className="font-semibold">
            {st.number} · {formatDate(st.period_start, i18n.language)} –{" "}
            {formatDate(st.period_end, i18n.language)}
          </h2>
          <p>
            {formatMoney(st.total, i18n.language)} · {t(`referrals.statementStatus.${st.status}`)}
          </p>
          <table className="w-full text-sm">
            <caption className="sr-only">{st.number}</caption>
            <thead>
              <tr>
                <Th>{t("referrals.partner.date")}</Th>
                <Th>{t("referrals.partner.line")}</Th>
                <Th>{t("referrals.partner.amount")}</Th>
              </tr>
            </thead>
            <tbody>
              {st.items.map((item, n) => (
                <tr key={n}>
                  <Td>{formatDate(item.earned_at, i18n.language)}</Td>
                  <Td>{item.description || t(`referrals.itemKinds.${item.kind}`)}</Td>
                  <Td>{formatMoney(item.amount, i18n.language)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}

export function AffiliatePayoutPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const me = useAffiliate();
  const [form, setForm] = useState({ payee: "", sortCode: "", account: "" });
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/portal/affiliate/payout", {
          body: {
            payee_name: form.payee,
            country: "GB",
            bank: { sort_code: form.sortCode, account_number: form.account },
          },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["portal", "affiliate"], data),
  });
  return (
    <form
      className="max-w-md space-y-3"
      aria-label={t("referrals.partner.nav.payout")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h1 className="text-xl font-semibold">{t("referrals.partner.nav.payout")}</h1>
      {me.data?.bank_hint ? (
        <p>{t("referrals.partner.current", { hint: me.data.bank_hint })}</p>
      ) : null}
      <TextField
        label={t("referrals.partner.payee")}
        required
        autoComplete="name"
        value={form.payee}
        onChange={(e) => setForm({ ...form, payee: e.target.value })}
      />
      <TextField
        label={t("referrals.partner.sortCode")}
        required
        inputMode="numeric"
        value={form.sortCode}
        onChange={(e) => setForm({ ...form, sortCode: e.target.value })}
      />
      <TextField
        label={t("referrals.partner.account")}
        required
        inputMode="numeric"
        value={form.account}
        onChange={(e) => setForm({ ...form, account: e.target.value })}
      />
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
      {save.isSuccess ? <p role="status">{t("referrals.saved")}</p> : null}
      <Button type="submit" disabled={save.isPending}>
        {t("referrals.partner.save")}
      </Button>
    </form>
  );
}
