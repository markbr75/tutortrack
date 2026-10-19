import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, applyBrandTheme, Button, cn, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import {
  BookOpen,
  Briefcase,
  CalendarClock,
  CalendarDays,
  ChartColumn,
  ChevronDown,
  CircleDashed,
  Clock,
  Copy,
  FileText,
  Gift,
  GraduationCap,
  Handshake,
  House,
  Inbox,
  ListChecks,
  type LucideIcon,
  MapPin,
  Megaphone,
  Menu,
  MessageSquarePlus,
  MessageSquareText,
  Newspaper,
  NotebookPen,
  Receipt,
  Settings,
  ShieldCheck,
  Sparkles,
  UserPlus,
  UserRound,
  Users,
  Wallet,
  X,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { NotificationBell } from "../comms/NotificationBell";
import { CommandPalette } from "../crm/CommandPalette";
import { CommandBar } from "../ai/CommandBar";
import { api, isAuthError, useMe, useMyOrganisations, useOrganisation } from "../api";
import { SubscriptionBanner } from "../subscription/SubscriptionBanner";
import { SuccessLayer } from "../success/SuccessLayer";
import { StatusBanner } from "./StatusBanner";
import { UpgradeDialog } from "../subscription/UpgradePrompts";

type Group = (typeof GROUPS)[number] | (typeof SETTINGS_GROUPS)[number] | "account";
type NavItem = {
  to: string;
  key: string;
  permission: string | null;
  group: Group;
  icon?: LucideIcon;
};

/** The sidebar's sections, in the order of the user guide ("grouped by job"). */
const GROUPS = [
  "main",
  "people",
  "scheduling",
  "lessons",
  "money",
  "sales",
  "comms",
  "insight",
] as const;
/** Settings has its own sub-menu, in the order of the admin guide. */
const SETTINGS_GROUPS = ["organisation", "teaching", "messages", "data", "trust"] as const;
/** Menus longer than this collapse to their group headings. */
const COLLAPSE_AFTER = 16;

// Each entry starts `{ to: "…", key: …` so `manage.py guides --check` can read the routes.
const NAV: NavItem[] = [
  { to: "/", key: "nav.home", permission: null, group: "main", icon: House },
  {
    to: "/clients",
    key: "nav.clients",
    permission: "people.client.view",
    group: "people",
    icon: Users,
  },
  {
    to: "/students",
    key: "nav.students",
    permission: "people.student.view",
    group: "people",
    icon: GraduationCap,
  },
  {
    to: "/tutors",
    key: "nav.tutors",
    permission: "people.tutor.view",
    group: "people",
    icon: UserRound,
  },
  {
    to: "/people/map",
    key: "peopleMap.nav",
    permission: "people.student.view",
    group: "people",
    icon: MapPin,
  },
  {
    to: "/people/duplicates",
    key: "peopleTools.duplicates.nav",
    permission: "people.merge",
    group: "people",
    icon: Copy,
  },
  {
    to: "/tasks",
    key: "nav.tasks",
    permission: "crm.task.view",
    group: "people",
    icon: ListChecks,
  },
  {
    to: "/calendar",
    key: "nav.calendar",
    permission: "scheduling.lesson.view",
    group: "scheduling",
    icon: CalendarDays,
  },
  {
    to: "/unconfirmed",
    key: "nav.unconfirmed",
    permission: "scheduling.lesson.complete",
    group: "scheduling",
    icon: CircleDashed,
  },
  {
    to: "/availability",
    key: "nav.availability",
    permission: "scheduling.availability.view",
    group: "scheduling",
    icon: Clock,
  },
  {
    to: "/requests",
    key: "nav.requests",
    permission: "scheduling.lesson.edit",
    group: "scheduling",
    icon: CalendarClock,
  },
  {
    to: "/jobs",
    key: "nav.jobs",
    permission: "jobs.job.view",
    group: "scheduling",
    icon: Briefcase,
  },
  {
    to: "/matching",
    key: "nav.matching",
    permission: "matching.search",
    group: "scheduling",
    icon: Handshake,
  },
  {
    to: "/reports",
    key: "nav.reports",
    permission: "delivery.report.view",
    group: "lessons",
    icon: FileText,
  },
  {
    to: "/lesson-feedback",
    key: "lessonFeedback.nav",
    permission: "delivery.feedback.view",
    group: "lessons",
    icon: MessageSquareText,
  },
  {
    to: "/courses",
    key: "nav.courses",
    permission: "courses.view",
    group: "lessons",
    icon: BookOpen,
  },
  {
    to: "/learning",
    key: "learning.nav",
    permission: "learning.homework.view",
    group: "lessons",
    icon: NotebookPen,
  },
  {
    to: "/billing",
    key: "nav.billing",
    permission: "billing.invoice.view",
    group: "money",
    icon: Receipt,
  },
  { to: "/payroll", key: "nav.payroll", permission: "payroll.view", group: "money", icon: Wallet },
  {
    to: "/leads",
    key: "nav.leads",
    permission: "leads.enquiry.view",
    group: "sales",
    icon: MessageSquarePlus,
  },
  {
    to: "/recruitment",
    key: "nav.recruitment",
    permission: "recruitment.application.view",
    group: "sales",
    icon: UserPlus,
  },
  {
    to: "/compliance",
    key: "nav.compliance",
    permission: "compliance.view",
    group: "sales",
    icon: ShieldCheck,
  },
  {
    to: "/growth",
    key: "referrals.nav",
    permission: "growth.affiliate.view",
    group: "sales",
    icon: Gift,
  },
  { to: "/inbox", key: "inbox.nav", permission: "comms.inbox.view", group: "comms", icon: Inbox },
  {
    to: "/broadcasts",
    key: "broadcasts.nav",
    permission: "comms.broadcast.view",
    group: "comms",
    icon: Megaphone,
  },
  {
    to: "/announcements",
    key: "nav.announcements",
    permission: "comms.announcement.manage",
    group: "comms",
    icon: Newspaper,
  },
  {
    to: "/analytics",
    key: "nav.analytics",
    permission: "reporting.dashboard.view",
    group: "insight",
    icon: ChartColumn,
  },
  {
    to: "/copilot",
    key: "ai.nav.copilot",
    permission: "ai.copilot",
    group: "insight",
    icon: Sparkles,
  },
  // Settings sub-menu.
  {
    to: "/settings",
    key: "settingsNav.organisation",
    permission: "org.settings.view",
    group: "organisation",
  },
  { to: "/team", key: "nav.team", permission: "team.view", group: "organisation" },
  { to: "/team/roles", key: "nav.roles", permission: "team.view", group: "organisation" },
  { to: "/settings/sso", key: "nav.sso", permission: "security.sso.manage", group: "organisation" },
  { to: "/audit", key: "nav.audit", permission: "audit.view", group: "organisation" },
  { to: "/settings/plan", key: "nav.plan", permission: "subscription.view", group: "organisation" },
  {
    to: "/settings/payments",
    key: "nav.payments",
    permission: "payments.provider.manage",
    group: "teaching",
  },
  { to: "/catalogue", key: "nav.catalogue", permission: "catalogue.view", group: "teaching" },
  {
    to: "/lesson-policies",
    key: "nav.deliverySettings",
    permission: "delivery.policy.manage",
    group: "teaching",
  },
  {
    to: "/settings/booking",
    key: "nav.booking",
    permission: "scheduling.booking.settings",
    group: "teaching",
  },
  {
    to: "/settings/accounting",
    key: "nav.accounting",
    permission: "integrations.accounting.view",
    group: "teaching",
  },
  {
    to: "/settings/notifications",
    key: "settingsNav.notifications",
    permission: "comms.settings.manage",
    group: "messages",
  },
  {
    to: "/settings/messaging",
    key: "messaging.nav",
    permission: "comms.channels.manage",
    group: "messages",
  },
  {
    to: "/settings/marketplace",
    key: "settingsNav.marketplace",
    permission: "org.settings.view",
    group: "messages",
  },
  {
    to: "/settings/integrations",
    key: "nav.integrations",
    permission: "integrations.personal",
    group: "messages",
  },
  {
    to: "/settings/ai",
    key: "ai.nav.settings",
    permission: "ai.settings.manage",
    group: "messages",
  },
  { to: "/automations", key: "nav.automations", permission: "automation.view", group: "messages" },
  { to: "/data", key: "nav.data", permission: "migration.import.view", group: "data" },
  { to: "/website", key: "nav.website", permission: "sites.view", group: "data" },
  { to: "/developer", key: "nav.developer", permission: "developer.webhook.view", group: "data" },
  { to: "/privacy", key: "privacyCentre.nav", permission: "privacy.dsar.manage", group: "trust" },
  { to: "/safeguarding", key: "safeguarding.nav", permission: "safeguarding.dsl", group: "trust" },
  // Reached from the user menu in the top bar.
  { to: "/account", key: "nav.account", permission: null, group: "account" },
];

const SETTINGS_ITEMS = NAV.filter((item) =>
  (SETTINGS_GROUPS as readonly string[]).includes(item.group),
);

function isActive(pathname: string, to: string): boolean {
  return to === "/" ? pathname === "/" : pathname === to || pathname.startsWith(`${to}/`);
}

/** The settings item a path belongs to (the longest match, so /team/roles is Roles). */
function settingsItemFor(pathname: string): NavItem | undefined {
  return SETTINGS_ITEMS.filter((item) => isActive(pathname, item.to)).sort(
    (a, b) => b.to.length - a.to.length,
  )[0];
}

function useAllowed(): (item: NavItem) => boolean {
  const { data } = useMe();
  const permissions = data?.permissions ?? {};
  return (item) => !item.permission || Boolean(permissions[item.permission]);
}

function NavLink({
  item,
  onNavigate,
  count = 0,
}: {
  item: NavItem;
  onNavigate?: () => void;
  count?: number;
}) {
  const { t } = useTranslation();
  const Icon = item.icon;
  return (
    <Link
      to={item.to}
      onClick={onNavigate}
      className="flex items-center gap-2.5 rounded-md px-2.5 py-1 text-sm text-shell-foreground hover:bg-shell-accent"
      // The current page carries the register's 1px red margin rule.
      activeProps={{
        className: "bg-shell-accent font-semibold shadow-[inset_1px_0_0_hsl(var(--tt-margin))]",
        "aria-current": "page",
      }}
      activeOptions={{ exact: item.to === "/" }}
    >
      {Icon ? (
        <Icon aria-hidden="true" className="size-4 shrink-0 text-shell-muted" strokeWidth={1.75} />
      ) : null}
      <span className="truncate">{t(item.key)}</span>
      {count > 0 ? (
        <>
          <span
            aria-hidden="true"
            className="ml-auto rounded-full bg-margin px-1.5 text-xs leading-4 font-semibold text-margin-foreground tabular-nums"
          >
            {count > 99 ? "99+" : count}
          </span>
          <span className="sr-only">{t("nav.waiting", { count })}</span>
        </>
      ) : null}
    </Link>
  );
}

const OPEN_GROUPS_KEY = "tt.nav.open";

/** Open on a first visit: the groups an office opens most. */
const DEFAULT_OPEN = ["people", "scheduling"];

function readOpenGroups(): string[] {
  try {
    const stored = window.localStorage.getItem(OPEN_GROUPS_KEY);
    if (stored === null) return DEFAULT_OPEN;
    const value: unknown = JSON.parse(stored);
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return DEFAULT_OPEN;
  }
}

/**
 * Long menus (agency roles) collapse to their group headings so every group fits the first
 * viewport; the group holding the current page opens itself, and opened groups are remembered.
 */
function useOpenGroups(pathname: string, collapsible: boolean) {
  const current = NAV.filter(
    (item) => (GROUPS as readonly string[]).includes(item.group) && isActive(pathname, item.to),
  ).sort((a, b) => b.to.length - a.to.length)[0]?.group;
  const [open, setOpen] = useState<string[]>(readOpenGroups);
  useEffect(() => {
    if (current && !open.includes(current)) setOpen((groups) => [...groups, current]);
    // Only a change of page opens its group; closing it again is the user's choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);
  useEffect(() => {
    try {
      window.localStorage.setItem(OPEN_GROUPS_KEY, JSON.stringify(open));
    } catch {
      // Private windows and blocked storage just forget the choice.
    }
  }, [open]);
  return {
    isOpen: (group: string) => !collapsible || group === "main" || open.includes(group),
    toggle: (group: string) =>
      setOpen((groups) =>
        groups.includes(group) ? groups.filter((g) => g !== group) : [...groups, group],
      ),
  };
}

/** Lists the user's other organisations; switching is navigation (FR-02-7). */
function OrgSwitcher() {
  const { t } = useTranslation();
  const { data: orgs = [] } = useMyOrganisations();
  if (orgs.length < 2) return null;
  return (
    <nav aria-label={t("switcher.label")} className="mt-2 text-sm">
      <p className="px-2.5 text-xs font-semibold uppercase tracking-wider text-shell-muted">
        {t("switcher.label")}
      </p>
      <ul className="mt-1">
        {orgs.map((org) => (
          <li key={org.id}>
            <a
              href={org.url}
              aria-current={org.is_current ? "page" : undefined}
              className="block rounded-md px-2.5 py-1 text-shell-foreground hover:bg-shell-accent aria-[current=page]:font-semibold"
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

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  const { data: org } = useOrganisation();
  const allowed = useAllowed();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const settings = SETTINGS_ITEMS.filter(allowed);
  const inSettings = Boolean(settingsItemFor(pathname));
  const visible = NAV.filter(
    (item) => (GROUPS as readonly string[]).includes(item.group) && allowed(item),
  ).length;
  const collapsible = visible > COLLAPSE_AFTER;
  const groups = useOpenGroups(pathname, collapsible);
  const canMark = allowed({
    to: "",
    key: "",
    group: "main",
    permission: "scheduling.lesson.complete",
  });
  // Shares Home's query, so the count and the Needs marking list agree.
  const waiting = useQuery({
    queryKey: ["home-unconfirmed"],
    enabled: canMark,
    staleTime: 60_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/unconfirmed-lessons")),
  });
  const unconfirmed = canMark ? (waiting.data?.length ?? 0) : 0;
  return (
    <div className="flex h-full flex-col bg-shell px-3 py-4 text-shell-foreground [&_:focus-visible]:outline-shell-foreground">
      <div className="flex items-center gap-2.5 border-b border-white/10 px-2.5 pb-4">
        <span
          aria-hidden="true"
          className="grid size-8 shrink-0 place-items-center rounded-md bg-shell-foreground text-sm font-bold text-shell"
        >
          {(org?.name ?? t("app.name")).slice(0, 1)}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-semibold">{org?.name ?? t("app.name")}</span>
          <span className="block text-xs text-shell-muted">{t("app.name")}</span>
        </span>
      </div>
      <nav
        aria-label="Main"
        className="mt-3 flex-1 overflow-y-auto pb-12 [mask-image:linear-gradient(to_bottom,black_calc(100%-2.5rem),transparent)] [scrollbar-width:thin]"
      >
        {GROUPS.map((group) => {
          const items = NAV.filter((item) => item.group === group && allowed(item));
          if (items.length === 0) return null;
          const heading = group === "main" ? null : t(`nav.groups.${group}`);
          const open = groups.isOpen(group);
          const countFor = (item: NavItem) => (item.to === "/unconfirmed" ? unconfirmed : 0);
          // A closed group still shows what is waiting inside it.
          const hiddenCount = open ? 0 : items.reduce((sum, item) => sum + countFor(item), 0);
          const label = "px-2.5 text-xs font-semibold uppercase tracking-wider text-shell-muted";
          return (
            <section
              key={group}
              aria-label={heading ?? undefined}
              className={group === "main" ? "" : "mt-3"}
            >
              {heading && collapsible ? (
                <h2>
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={`nav-${group}`}
                    onClick={() => groups.toggle(group)}
                    className={cn(
                      label,
                      "flex w-full items-center justify-between rounded-md py-1 hover:text-shell-foreground",
                    )}
                  >
                    <span className="flex items-center gap-2">
                      {heading}
                      {hiddenCount > 0 ? (
                        <>
                          <span
                            aria-hidden="true"
                            className="rounded-full bg-margin px-1.5 text-xs leading-4 font-semibold tracking-normal text-margin-foreground normal-case tabular-nums"
                          >
                            {hiddenCount > 99 ? "99+" : hiddenCount}
                          </span>
                          <span className="sr-only">
                            {t("nav.waiting", { count: hiddenCount })}
                          </span>
                        </>
                      ) : null}
                    </span>
                    <ChevronDown
                      aria-hidden="true"
                      className={cn(
                        "size-3.5 transition-transform duration-150",
                        open ? "" : "-rotate-90",
                      )}
                    />
                  </button>
                </h2>
              ) : heading ? (
                <h2 className={cn(label, "pb-1")}>{heading}</h2>
              ) : null}
              {open ? (
                <ul id={`nav-${group}`} className="space-y-px">
                  {items.map((item) => (
                    <li key={item.to}>
                      <NavLink item={item} onNavigate={onNavigate} count={countFor(item)} />
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          );
        })}
      </nav>
      <div className="mt-3 border-t border-white/10 pt-3">
        {settings.length > 0 ? (
          <Link
            to={settings[0]!.to}
            onClick={onNavigate}
            aria-current={inSettings ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm hover:bg-shell-accent",
              inSettings && "bg-shell-accent font-semibold",
            )}
          >
            <Settings aria-hidden="true" className="size-4 text-shell-muted" strokeWidth={1.75} />
            {t("nav.settingsArea")}
          </Link>
        ) : null}
        <OrgSwitcher />
      </div>
    </div>
  );
}

function UserMenu() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const logout = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/auth/logout")),
    onSettled: () => window.location.assign("/login"),
  });
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (
        event instanceof KeyboardEvent
          ? event.key === "Escape"
          : !ref.current?.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  const user = me?.user;
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.email || "";
  const initials = name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-1.5 rounded-full p-0.5 pr-1.5 hover:bg-muted"
      >
        <span
          aria-hidden="true"
          className="grid size-8 place-items-center rounded-full bg-shell text-xs font-semibold text-shell-foreground"
        >
          {initials || "?"}
        </span>
        <span className="sr-only">{t("nav.userMenu", { name })}</span>
        <ChevronDown aria-hidden="true" className="size-4 text-muted-foreground" />
      </button>
      {open ? (
        <div className="absolute right-0 z-30 mt-2 w-56 rounded-lg border border-border bg-surface p-1 text-sm shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)]">
          <p className="truncate px-3 py-2 text-muted-foreground">{name}</p>
          <Link
            to="/account"
            onClick={() => setOpen(false)}
            className="block rounded-md px-3 py-2 hover:bg-muted"
          >
            {t("nav.account")}
          </Link>
          <button
            type="button"
            className="block w-full rounded-md px-3 py-2 text-left hover:bg-muted"
            onClick={() => logout.mutate()}
          >
            {t("nav.signOut")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Phones and narrow windows: the sidebar opens as a drawer from the top bar. */
function MobileMenu() {
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
        // Mounted only while open, so the page never carries a second "Main" navigation.
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
            <Sidebar onNavigate={() => setOpen(false)} />
          </div>
        </dialog>
      ) : null}
    </>
  );
}

function TopBar({ permissions }: { permissions: Partial<Record<string, string>> }) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-border bg-background/95 px-3 backdrop-blur-sm md:gap-3 md:px-6">
      <MobileMenu />
      {permissions["crm.search"] ? <CommandPalette /> : null}
      {permissions["ai.use"] ? <CommandBar /> : null}
      <div className="flex-1" />
      <SuccessLayer />
      <NotificationBell />
      <UserMenu />
    </header>
  );
}

/** Settings pages share a sub-menu, grouped as in the admin guide. */
function SettingsLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const allowed = useAllowed();
  return (
    <div className="grid gap-8 lg:grid-cols-[13rem_1fr]">
      <nav aria-label={t("nav.settingsArea")} className="text-sm lg:sticky lg:top-20 lg:self-start">
        <h2 className="mb-3 text-base font-semibold">{t("nav.settingsArea")}</h2>
        {SETTINGS_GROUPS.map((group) => {
          const items = SETTINGS_ITEMS.filter((item) => item.group === group && allowed(item));
          if (items.length === 0) return null;
          return (
            <section key={group} className="mb-4">
              <h3 className="px-2.5 pb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {t(`settingsNav.groups.${group}`)}
              </h3>
              <ul>
                {items.map((item) => (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      className="block rounded-md px-2.5 py-1.5 hover:bg-muted"
                      activeProps={{
                        className: "bg-muted font-semibold text-foreground",
                        "aria-current": "page",
                      }}
                      activeOptions={{ exact: item.to === "/settings" || item.to === "/team" }}
                    >
                      {t(item.key)}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </nav>
      <div className="min-w-0">{children}</div>
    </div>
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
  const pathname = useRouterState({ select: (s) => s.location.pathname });
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
  const inSettings = Boolean(settingsItemFor(pathname));
  const page = <Outlet />;

  return (
    <div className="min-h-dvh text-sm md:grid md:grid-cols-[15.5rem_1fr]">
      <aside className="hidden md:sticky md:top-0 md:block md:h-dvh">
        <Sidebar />
      </aside>
      <div className="min-w-0">
        <TopBar permissions={permissions} />
        <main className="mx-auto max-w-[96rem] px-4 py-6 md:px-8 md:py-8">
          <ImpersonationBanner />
          <StatusBanner />
          <SuspendedBanner />
          <SubscriptionBanner />
          {inSettings ? <SettingsLayout>{page}</SettingsLayout> : page}
          <UpgradeDialog />
        </main>
      </div>
    </div>
  );
}
