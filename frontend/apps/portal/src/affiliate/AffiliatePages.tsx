import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  figureCell,
  PanelFooter,
  RuledPanel,
  RuledTable,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { FileText, House, Landmark, Users } from "lucide-react";
import { useEffect, useState } from "react";

import { api, problemStatus } from "../api";
import { BrandMark, PoweredBy } from "../branding";
import { PortalFrame } from "../layout/PortalFrame";
import { PortalHeader, useIsPhone, Word } from "../layout/PortalPage";
import { CopyLink } from "../pages/ReferralsPage";

function useAffiliate() {
  return useQuery({
    queryKey: ["portal", "affiliate"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/affiliate")),
  });
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

/** Clients a partner referred: a framed ruled table (joined and first payment fold into the
 * client's caption on phones). */
export function AffiliateClientsPage() {
  const { t, i18n } = useTranslation();
  const phone = useIsPhone();
  const clients = useQuery({
    queryKey: ["portal", "affiliate", "clients"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/affiliate/clients")),
  });
  if (!clients.data) return <Spinner label={t("grid.loading")} />;
  const date = (iso: string) => formatDate(iso, i18n.language);
  const dash = <span className="text-muted-foreground">–</span>;
  return (
    <div>
      <PortalHeader title={t("referrals.partner.nav.clients")} />
      <RuledTable
        framed
        caption={t("referrals.partner.nav.clients")}
        columns={[
          { key: "client", header: t("referrals.partner.client") },
          ...(phone
            ? []
            : [
                { key: "joined", header: t("referrals.partner.joined") },
                { key: "first", header: t("referrals.partner.firstPayment") },
              ]),
          { key: "commission", header: t("referrals.partner.commission"), end: true, width: "w-32" },
        ]}
        empty={clients.data.length ? undefined : t("referrals.partner.noClients")}
      >
        {clients.data.map((c) => (
          <tr key={c.id}>
            <td>
              <span className="font-medium">{c.name}</span>
              {phone ? (
                <span className="block text-xs text-muted-foreground tabular-nums">
                  {[
                    date(c.attributed_at),
                    c.converted_at ? date(c.converted_at) : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              ) : null}
            </td>
            {phone ? null : (
              <>
                <td className="tabular-nums">{date(c.attributed_at)}</td>
                <td className="tabular-nums">{c.converted_at ? date(c.converted_at) : dash}</td>
              </>
            )}
            <td className={figureCell}>
              {c.commission ? formatMoney(c.commission, i18n.language) : dash}
            </td>
          </tr>
        ))}
      </RuledTable>
    </div>
  );
}

/** Each statement as a ruled panel: its number and period, the status in words, its lines
 * and the total in the amount column. */
export function AffiliateStatementsPage() {
  const { t, i18n } = useTranslation();
  const statements = useQuery({
    queryKey: ["portal", "affiliate", "statements"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/affiliate/statements")),
  });
  if (!statements.data) return <Spinner label={t("grid.loading")} />;
  const date = (iso: string) => formatDate(iso, i18n.language);
  return (
    <div>
      <PortalHeader title={t("referrals.partner.nav.statements")} />
      {!statements.data.length ? (
        <p className="text-sm text-muted-foreground">{t("referrals.partner.noStatements")}</p>
      ) : null}
      <div className="space-y-6">
        {statements.data.map((st) => (
          <RuledPanel
            key={st.id}
            titleId={`st-${st.id}`}
            title={<span className="tabular-nums">{st.number}</span>}
            description={
              <span className="tabular-nums">
                {date(st.period_start)} – {date(st.period_end)}
              </span>
            }
            aside={
              <Word className="text-foreground">
                {t(`referrals.statementStatus.${st.status}`)}
              </Word>
            }
            flush
          >
            <RuledTable
              caption={st.number}
              columns={[
                { key: "date", header: t("referrals.partner.date"), width: "w-32" },
                { key: "line", header: t("referrals.partner.line") },
                { key: "amount", header: t("referrals.partner.amount"), end: true, width: "w-32" },
              ]}
              footer={
                <tr>
                  <td colSpan={2} className="text-right font-semibold">
                    {t("designS10.total")}
                  </td>
                  <td className={`${figureCell} font-semibold`}>
                    {formatMoney(st.total, i18n.language)}
                  </td>
                </tr>
              }
            >
              {st.items.map((item, n) => (
                <tr key={n}>
                  <td className="whitespace-nowrap tabular-nums">{date(item.earned_at)}</td>
                  <td>{item.description || t(`referrals.itemKinds.${item.kind}`)}</td>
                  <td className={figureCell}>{formatMoney(item.amount, i18n.language)}</td>
                </tr>
              ))}
            </RuledTable>
          </RuledPanel>
        ))}
      </div>
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
    <div>
      <PortalHeader
        title={t("referrals.partner.nav.payout")}
        description={
          me.data?.bank_hint
            ? t("referrals.partner.current", { hint: me.data.bank_hint })
            : undefined
        }
      />
      <form
        aria-label={t("referrals.partner.nav.payout")}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <RuledPanel label={t("referrals.partner.nav.payout")} flush>
          <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-3">
            <TextField
              label={t("referrals.partner.payee")}
              required
              autoComplete="name"
              value={form.payee}
              onChange={(e) => setForm({ ...form, payee: e.target.value })}
            />
            <TextField
              label={t("referrals.partner.sortCode")}
              className="tabular-nums"
              required
              inputMode="numeric"
              value={form.sortCode}
              onChange={(e) => setForm({ ...form, sortCode: e.target.value })}
            />
            <TextField
              label={t("referrals.partner.account")}
              className="tabular-nums"
              required
              inputMode="numeric"
              value={form.account}
              onChange={(e) => setForm({ ...form, account: e.target.value })}
            />
          </div>
          {save.error ? (
            <div className="px-5 pb-4">
              <Alert tone="danger">{save.error.message}</Alert>
            </div>
          ) : null}
          <PanelFooter>
            <Button type="submit" disabled={save.isPending}>
              {t("referrals.partner.save")}
            </Button>
            <span role="status" className="text-sm text-success">
              {save.isSuccess ? t("referrals.saved") : ""}
            </span>
          </PanelFooter>
        </RuledPanel>
      </form>
    </div>
  );
}
