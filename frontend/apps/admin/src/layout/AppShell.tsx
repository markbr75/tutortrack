import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, applyBrandTheme, Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, Outlet } from "@tanstack/react-router";
import { useEffect } from "react";

import { NotificationBell } from "../comms/NotificationBell";
import { CommandPalette } from "../crm/CommandPalette";
import { CommandBar } from "../ai/CommandBar";
import { api, isAuthError, useMe, useMyOrganisations, useOrganisation } from "../api";
import { SubscriptionBanner } from "../subscription/SubscriptionBanner";
import { StatusBanner } from "./StatusBanner";
import { UpgradeDialog } from "../subscription/UpgradePrompts";

const NAV = [
  { to: "/", key: "nav.home", permission: null },
  { to: "/calendar", key: "nav.calendar", permission: "scheduling.lesson.view" },
  { to: "/clients", key: "nav.clients", permission: "people.client.view" },
  { to: "/students", key: "nav.students", permission: "people.student.view" },
  { to: "/tutors", key: "nav.tutors", permission: "people.tutor.view" },
  { to: "/people/map", key: "peopleMap.nav", permission: "people.student.view" },
  { to: "/jobs", key: "nav.jobs", permission: "jobs.job.view" },
  { to: "/courses", key: "nav.courses", permission: "courses.view" },
  { to: "/growth", key: "referrals.nav", permission: "growth.affiliate.view" },
  { to: "/learning", key: "learning.nav", permission: "learning.homework.view" },
  { to: "/billing", key: "nav.billing", permission: "billing.invoice.view" },
  { to: "/payroll", key: "nav.payroll", permission: "payroll.view" },
  { to: "/leads", key: "nav.leads", permission: "leads.enquiry.view" },
  { to: "/recruitment", key: "nav.recruitment", permission: "recruitment.application.view" },
  { to: "/compliance", key: "nav.compliance", permission: "compliance.view" },
  { to: "/matching", key: "nav.matching", permission: "matching.search" },
  { to: "/automations", key: "nav.automations", permission: "automation.view" },
  { to: "/tasks", key: "nav.tasks", permission: "crm.task.view" },
  { to: "/inbox", key: "inbox.nav", permission: "comms.inbox.view" },
  { to: "/broadcasts", key: "broadcasts.nav", permission: "comms.broadcast.view" },
  { to: "/announcements", key: "nav.announcements", permission: "comms.announcement.manage" },
  { to: "/analytics", key: "nav.analytics", permission: "reporting.dashboard.view" },
  { to: "/copilot", key: "ai.nav.copilot", permission: "ai.copilot" },
  { to: "/reports", key: "nav.reports", permission: "delivery.report.view" },
  { to: "/lesson-feedback", key: "lessonFeedback.nav", permission: "delivery.feedback.view" },
  { to: "/unconfirmed", key: "nav.unconfirmed", permission: "scheduling.lesson.complete" },
  { to: "/availability", key: "nav.availability", permission: "scheduling.availability.view" },
  { to: "/requests", key: "nav.requests", permission: "scheduling.lesson.edit" },
  { to: "/catalogue", key: "nav.catalogue", permission: "catalogue.view" },
  { to: "/lesson-policies", key: "nav.deliverySettings", permission: "delivery.policy.manage" },
  { to: "/team", key: "nav.team", permission: "team.view" },
  { to: "/team/roles", key: "nav.roles", permission: "team.view" },
  { to: "/audit", key: "nav.audit", permission: "audit.view" },
  { to: "/privacy", key: "privacyCentre.nav", permission: "privacy.dsar.manage" },
  { to: "/safeguarding", key: "safeguarding.nav", permission: "safeguarding.dsl" },
  { to: "/settings/payments", key: "nav.payments", permission: "payments.provider.manage" },
  { to: "/settings/booking", key: "nav.booking", permission: "scheduling.booking.settings" },
  { to: "/settings/sso", key: "nav.sso", permission: "security.sso.manage" },
  {
    to: "/settings/notifications",
    key: "nav.notifications",
    permission: "comms.settings.manage",
  },
  {
    to: "/settings/integrations",
    key: "nav.integrations",
    permission: "integrations.personal",
  },
  {
    to: "/settings/accounting",
    key: "nav.accounting",
    permission: "integrations.accounting.view",
  },
  { to: "/settings/messaging", key: "messaging.nav", permission: "comms.channels.manage" },
  { to: "/settings/ai", key: "ai.nav.settings", permission: "ai.settings.manage" },
  { to: "/data", key: "nav.data", permission: "migration.import.view" },
  { to: "/settings/plan", key: "nav.plan", permission: "subscription.view" },
  { to: "/settings/marketplace", key: "nav.marketplace", permission: "org.settings.view" },
  { to: "/website", key: "nav.website", permission: "sites.view" },
  { to: "/developer", key: "nav.developer", permission: "developer.webhook.view" },
  { to: "/settings", key: "nav.settings", permission: "org.settings.view" },
  { to: "/account", key: "nav.account", permission: null },
] as const;
/** Lists the user's other organisations; switching is navigation (FR-02-7). */
function OrgSwitcher() {
  const { t } = useTranslation();
  const { data: orgs = [] } = useMyOrganisations();
  if (orgs.length < 2) return null;
  return (
    <nav aria-label={t("switcher.label")} className="mt-auto pt-4 text-sm">
      <p className="px-2 text-xs font-medium text-muted-foreground">{t("switcher.label")}</p>
      <ul>
        {orgs.map((org) => (
          <li key={org.id}>
            <a
              href={org.url}
              aria-current={org.is_current ? "page" : undefined}
              className="block rounded-md px-2 py-1 hover:bg-muted aria-[current=page]:font-medium"
            >
              {org.name}
              {org.is_current ? <span className="sr-only"> ({t("switcher.current")})</span> : null}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function SuspendedBanner() {
  const { t } = useTranslation();
  const { data: org } = useOrganisation();
  if (org?.status !== "suspended") return null;
  return (
    <Alert tone="warning" title={t("suspended.title")} className="mb-6">
      {t("suspended.body")}
    </Alert>
  );
}

function SignInRequired() {
  const { t } = useTranslation();
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  useEffect(() => {
    window.location.assign(`/login?next=${next}`);
  }, [next]);
  return (
    <main className="mx-auto mt-24 max-w-sm px-4 text-center">
      <h1 className="text-2xl font-semibold">{t("auth.signInTitle")}</h1>
      <p className="mt-2 text-muted-foreground">{t("auth.signInBody")}</p>
      <a className="mt-6 inline-block underline" href={`/login?next=${next}`}>
        {t("auth.signInAction")}
      </a>
    </main>
  );
}

function ImpersonationBanner() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const stop = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/impersonate/stop")),
    onSuccess: () => window.location.assign("/team"),
  });
  if (!me?.impersonator) return null;
  const name = [me.user.first_name, me.user.last_name].filter(Boolean).join(" ") || me.user.email;
  return (
    <Alert tone="warning" className="mb-6 flex flex-wrap items-center justify-between gap-2">
      <span>
        {t("impersonation.banner", { name })}{" "}
        {!me.impersonator.write ? t("impersonation.readOnly") : null}
      </span>
      <Button size="sm" variant="secondary" onClick={() => stop.mutate()}>
        {t("impersonation.stop")}
      </Button>
    </Alert>
  );
}

function SignOut() {
  const { t } = useTranslation();
  const logout = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/auth/logout")),
    onSettled: () => window.location.assign("/login"),
  });
  return (
    <button
      type="button"
      className="rounded-md px-2 py-1 text-left text-sm hover:bg-muted"
      onClick={() => logout.mutate()}
    >
      {t("nav.signOut")}
    </button>
  );
}

/** The admin app takes the brand colour subtly (buttons and accents only, E24 FR-24-1). */
function useSubtleBranding(enabled: boolean) {
  const brand = useQuery({
    queryKey: ["public-branding"],
    queryFn: async () => unwrap(await api.GET("/api/v1/public/branding")),
    enabled,
    staleTime: 10 * 60_000,
  });
  useEffect(() => {
    if (brand.data) applyBrandTheme(brand.data);
  }, [brand.data]);
}

export function AppShell() {
  const { t } = useTranslation();
  const session = useMe();
  const permissions = session.data?.permissions ?? {};
  useSubtleBranding(Boolean(session.data));

  if (session.isPending) {
    return (
      <div className="grid h-screen place-items-center">
        <Spinner className="size-6" label={t("grid.loading")} />
      </div>
    );
  }
  if (session.isError && isAuthError(session.error)) {
    return <SignInRequired />;
  }
  const role = session.data?.membership?.role ?? "";
  if (["client", "student", "tutor"].includes(role)) {
    // Families (E15) and tutors (E16) use the portal app.
    window.location.replace(role === "tutor" ? "/portal/tutor" : "/portal/");
    return null;
  }

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <nav
        aria-label="Main"
        className="flex gap-1 border-b border-border p-3 md:w-56 md:flex-col md:border-r md:border-b-0"
      >
        <span className="mr-4 px-2 py-1 font-semibold md:mb-4 md:mr-0">{t("app.name")}</span>
        {permissions["crm.search"] ? <CommandPalette /> : null}
        {permissions["ai.use"] ? <CommandBar /> : null}
        <NotificationBell />
        {NAV.filter((item) => !item.permission || permissions[item.permission]).map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className="rounded-md px-2 py-1 text-sm hover:bg-muted"
            activeProps={{ className: "bg-muted font-medium" }}
            activeOptions={{ exact: item.to === "/" }}
          >
            {t(item.key)}
          </Link>
        ))}
        <OrgSwitcher />
        <SignOut />
      </nav>
      <main className="flex-1 p-4 md:p-8">
        <ImpersonationBanner />
        <StatusBanner />
        <SuspendedBanner />
        <SubscriptionBanner />
        <Outlet />
        <UpgradeDialog />
      </main>
    </div>
  );
}
