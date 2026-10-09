import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner } from "@tutortrack/ui";
import { Link, Outlet } from "@tanstack/react-router";

import { isAuthError, useFeatures, useMyOrganisations, useOrganisation } from "../api";

const NAV = [
  { to: "/", key: "nav.home" },
  { to: "/audit", key: "nav.audit" },
  { to: "/settings", key: "nav.settings" },
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
              {org.is_current ? (
                <span className="sr-only"> ({t("switcher.current")})</span>
              ) : null}
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
  const next = encodeURIComponent(window.location.pathname);
  return (
    <main className="mx-auto mt-24 max-w-sm px-4 text-center">
      <h1 className="text-2xl font-semibold">{t("auth.signInTitle")}</h1>
      <p className="mt-2 text-muted-foreground">{t("auth.signInBody")}</p>
      {/* E03 replaces this with the real login screen. */}
      <Button
        className="mt-6"
        onClick={() => window.location.assign(`/django-admin/login/?next=${next}`)}
      >
        {t("auth.signInAction")}
      </Button>
    </main>
  );
}

export function AppShell() {
  const { t } = useTranslation();
  const session = useFeatures();

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

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <nav
        aria-label="Main"
        className="flex gap-1 border-b border-border p-3 md:w-56 md:flex-col md:border-r md:border-b-0"
      >
        <span className="mr-4 px-2 py-1 font-semibold md:mb-4 md:mr-0">{t("app.name")}</span>
        {NAV.map((item) => (
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
      </nav>
      <main className="flex-1 p-4 md:p-8">
        <SuspendedBanner />
        <Outlet />
      </main>
    </div>
  );
}
