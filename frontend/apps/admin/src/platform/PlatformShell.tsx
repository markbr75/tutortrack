import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  Building2,
  Coins,
  Flag,
  HeartPulse,
  LifeBuoy,
  LineChart,
  Megaphone,
  Menu,
  MessageSquare,
  Package,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, isAuthError } from "../api";
import { AccountMenu } from "../layout/AccountMenu";
import { LoadingLine } from "../layout/AppShell";

interface ConsoleItem {
  to: string;
  key: string;
  icon: LucideIcon;
}

/** The console's destinations, grouped by job like the admin rail. */
const GROUPS: ReadonlyArray<{ key: string; items: ReadonlyArray<ConsoleItem> }> = [
  {
    key: "customers",
    items: [
      { to: "/platform", key: "platform.nav.tenants", icon: Building2 },
      { to: "/platform/health", key: "tenantHealth.nav", icon: HeartPulse },
      { to: "/platform/support", key: "supportInbox.nav", icon: LifeBuoy },
      { to: "/platform/customer-notices", key: "customerNotices.nav", icon: Megaphone },
    ],
  },
  {
    key: "product",
    items: [
      { to: "/platform/plans", key: "platformPlans.nav", icon: Package },
      { to: "/platform/flags", key: "platform.nav.flags", icon: Flag },
      { to: "/platform/feedback", key: "productInsights.nav", icon: MessageSquare },
    ],
  },
  {
    key: "revenue",
    items: [
      { to: "/platform/metrics", key: "saasMetrics.nav", icon: LineChart },
      { to: "/platform/revenue-share", key: "revenueShare.nav", icon: Coins },
    ],
  },
  {
    key: "operations",
    items: [
      { to: "/platform/operations", key: "platform.nav.operations", icon: Activity },
      { to: "/platform/workflows", key: "workflowConsole.nav", icon: Workflow },
    ],
  },
];

/** The bookcloth rail: TutorTrack's name, then the console's groups. */
function ConsoleRail({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full flex-col bg-shell px-3 py-4 text-shell-foreground [&_:focus-visible]:outline-shell-foreground">
      <div className="flex items-center gap-2.5 border-b border-shell-rule px-2.5 pb-4">
        <span
          aria-hidden="true"
          className="grid size-8 shrink-0 place-items-center rounded-md bg-shell-foreground text-sm font-bold text-shell"
        >
          {t("app.name").slice(0, 1)}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-semibold">{t("app.name")}</span>
          <span className="block text-xs text-shell-muted">{t("designS11.platform.console")}</span>
        </span>
      </div>
      <nav
        aria-label={t("platform.title")}
        className="mt-3 flex-1 overflow-y-auto pb-12 [scrollbar-width:thin]"
      >
        {GROUPS.map((group, index) => (
          <section
            key={group.key}
            aria-label={t(`designS11.platform.groups.${group.key}`)}
            className={index ? "mt-3" : undefined}
          >
            <h2 className="px-2.5 pb-1 text-xs font-semibold tracking-wider text-shell-muted uppercase">
              {t(`designS11.platform.groups.${group.key}`)}
            </h2>
            <ul className="space-y-px">
              {group.items.map((item) => (
                <li key={item.to}>
                  <Link
                    to={item.to}
                    onClick={onNavigate}
                    className="flex items-center gap-2.5 rounded-md px-2.5 py-1 text-sm text-shell-foreground hover:bg-shell-accent"
                    // The current page carries the register's 1px red margin rule.
                    activeProps={{
                      className:
                        "bg-shell-accent font-semibold shadow-[inset_1px_0_0_hsl(var(--tt-margin))]",
                      "aria-current": "page",
                    }}
                    activeOptions={{ exact: item.to === "/platform" }}
                  >
                    <item.icon
                      aria-hidden="true"
                      className="size-4 shrink-0 text-shell-muted"
                      strokeWidth={1.75}
                    />
                    <span className="truncate">{t(item.key)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>
    </div>
  );
}

/** Phones: the rail opens as a drawer from the top bar, mounted only while open. */
function ConsoleMenu() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  useEffect(() => {
    if (open) dialog.current?.showModal();
  }, [open]);
  useEffect(() => setOpen(false), [pathname]);
  return (
    <>
      <button
        type="button"
        className="grid size-9 place-items-center rounded-md hover:bg-muted md:hidden"
        aria-label={t("nav.openMenu")}
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <Menu aria-hidden="true" className="size-5" />
      </button>
      {open ? (
        <dialog
          ref={dialog}
          aria-label={t("nav.menu")}
          onClose={() => setOpen(false)}
          className="m-0 h-dvh max-h-none w-72 max-w-[85vw] bg-shell p-0 backdrop:bg-black/40"
        >
          <div className="relative h-full">
            <button
              type="button"
              className="absolute top-3 right-3 z-10 grid size-9 place-items-center rounded-md text-shell-foreground hover:bg-shell-accent"
              aria-label={t("nav.closeMenu")}
              onClick={() => setOpen(false)}
            >
              <X aria-hidden="true" className="size-5" />
            </button>
            <ConsoleRail onNavigate={() => setOpen(false)} />
          </div>
        </dialog>
      ) : null}
    </>
  );
}

/** The TutorTrack staff console (E30): platform staff with 2FA, from allowed networks. */
export function PlatformShell() {
  const { t } = useTranslation();
  const me = useQuery({
    queryKey: ["platform", "me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/me")),
    retry: false,
  });
  const signedOut = me.isError && isAuthError(me.error);
  useEffect(() => {
    if (signedOut) window.location.assign("/login?next=%2Fplatform");
  }, [signedOut]);
  useEffect(() => {
    document.title = t("platform.title");
  }, [t]);

  if (me.isPending || signedOut) {
    return (
      <div className="grid h-dvh place-items-center">
        <Spinner label={t("grid.loading")} />
      </div>
    );
  }
  const access = me.data;
  const problem = !access?.is_platform_staff
    ? t("platform.notStaff")
    : !access.mfa_verified
      ? t("platform.needsMfa")
      : !access.network_allowed
        ? t("platform.wrongNetwork")
        : null;
  return (
    <div className="min-h-dvh text-sm md:grid md:grid-cols-[15.5rem_1fr]">
      {problem ? null : (
        <aside className="hidden md:sticky md:top-0 md:block md:h-dvh">
          <ConsoleRail />
        </aside>
      )}
      <div className={problem ? "md:col-span-2" : "min-w-0"}>
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-border bg-background/95 px-3 backdrop-blur-sm md:px-6">
          {problem ? (
            <span className="font-semibold">{t("platform.title")}</span>
          ) : (
            <>
              <ConsoleMenu />
              <span className="font-semibold md:hidden">{t("platform.title")}</span>
            </>
          )}
          <div className="flex-1" />
          {access?.email ? (
            // Staff have an email, not a name: it heads the menu and names the disc.
            <AccountMenu name={access.email} afterSignOut="/login?next=%2Fplatform" />
          ) : null}
          <LoadingLine />
        </header>
        <main className="mx-auto max-w-[96rem] px-4 py-6 md:px-8 md:py-8">
          {problem ? (
            <Alert tone="danger" className="max-w-2xl">
              {problem}
            </Alert>
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </div>
  );
}
