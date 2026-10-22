import { useTranslation } from "@tutortrack/i18n";
import { cn } from "@tutortrack/ui";
import { Link, useRouterState } from "@tanstack/react-router";
import { Ellipsis, LogOut, X, type LucideIcon } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { CountPill } from "./PortalPage";

export interface PortalNavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Heading key in `groups`; items without one are listed first. */
  group?: string;
  /** Waiting items (unread messages, lessons to mark): a margin-red count pill. */
  count?: number;
}

export interface PortalFrameProps {
  /** Logo or business name. */
  brand: ReactNode;
  /** Accessible name of the navigation landmark. */
  navLabel: string;
  items: ReadonlyArray<PortalNavItem>;
  /** Paths in order of everyday use; the first four available become the phone tabs. */
  primary: ReadonlyArray<string>;
  /** Group headings for the More sheet and the desktop rail. */
  groups?: Readonly<Record<string, string>>;
  /** The route that matches only exactly ("/" or "/tutor"). */
  root: string;
  /** The signed-in person's name, for the account menu. */
  person: string;
  onSignOut: () => void;
  /** Extra header controls (the household switcher). */
  headerExtra?: ReactNode;
  /** Banners under the header (offline, status). */
  banner?: ReactNode;
  /** Help, terms and the "Powered by" credit. */
  footer?: ReactNode;
  children: ReactNode;
}

const WIDE = "(min-width: 768px)";

/** Phones get the tab bar, wider screens the rail. Without matchMedia (tests) the rail shows,
 * so every destination is a plain link on the page. */
function useWide(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia?.(WIDE);
      query?.addEventListener("change", notify);
      return () => query?.removeEventListener("change", notify);
    },
    () => window.matchMedia?.(WIDE).matches ?? true,
  );
}

function usePathname(): string {
  return useRouterState({ select: (s) => s.location.pathname });
}

function isCurrent(pathname: string, to: string, root: string): boolean {
  if (to === root) return pathname === root || pathname === `${root}/`;
  return pathname === to || pathname.startsWith(`${to}/`);
}

/** The portal's shell for every role: a header with the business's mark, the phone tab bar
 * with a More sheet, or a rail on wider screens. One navigation landmark at a time. */
export function PortalFrame({
  brand,
  navLabel,
  items,
  primary,
  groups = {},
  root,
  person,
  onSignOut,
  headerExtra,
  banner,
  footer,
  children,
}: PortalFrameProps) {
  const wide = useWide();
  const pathname = usePathname();
  const available = new Set(items.map((item) => item.to));
  const tabPaths =
    items.length <= 5
      ? items.map((item) => item.to)
      : primary.filter((to) => available.has(to)).slice(0, 4);
  const tabs = tabPaths.map((to) => items.find((item) => item.to === to)!);
  const rest = items.filter((item) => !tabPaths.includes(item.to));

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_minmax(0,1fr)]">
      {wide ? (
        <Rail
          brand={brand}
          navLabel={navLabel}
          items={items}
          groups={groups}
          root={root}
          pathname={pathname}
        />
      ) : null}
      <div className="flex min-h-dvh min-w-0 flex-col">
        <header className="sticky top-0 z-20 border-b border-border bg-surface pt-[env(safe-area-inset-top)]">
          <div className="mx-auto flex h-14 max-w-3xl items-center gap-3 px-4 md:max-w-none md:px-8">
            <div className="min-w-0 flex-1 truncate">{wide ? null : brand}</div>
            {headerExtra}
            <AccountMenu person={person} onSignOut={onSignOut} />
          </div>
        </header>
        {banner}
        <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-6 md:px-8 md:py-8">
          {children}
        </main>
        {footer ? <div className="mx-auto w-full max-w-3xl">{footer}</div> : null}
        {/* Room for the tab bar, so the last row never hides behind it. */}
        {wide ? null : <div aria-hidden="true" className="h-20 shrink-0" />}
      </div>
      {wide ? null : (
        <TabBar
          navLabel={navLabel}
          tabs={tabs}
          rest={rest}
          groups={groups}
          root={root}
          pathname={pathname}
        />
      )}
    </div>
  );
}

function Rail({
  brand,
  navLabel,
  items,
  groups,
  root,
  pathname,
}: {
  brand: ReactNode;
  navLabel: string;
  items: ReadonlyArray<PortalNavItem>;
  groups: Readonly<Record<string, string>>;
  root: string;
  pathname: string;
}) {
  const sections = groupItems(items);
  return (
    <aside className="sticky top-0 flex h-dvh flex-col border-r border-border bg-surface">
      <div className="flex h-14 shrink-0 items-center border-b border-border px-5">
        <div className="min-w-0 truncate">{brand}</div>
      </div>
      <nav aria-label={navLabel} className="flex-1 overflow-y-auto px-3 py-4">
        {sections.map(([group, list]) => (
          <div key={group || "top"} className={group ? "mt-5" : undefined}>
            {group ? (
              <h2 className="px-3 pb-1.5 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                {groups[group] ?? group}
              </h2>
            ) : null}
            <ul className="space-y-0.5">
              {list.map((item) => {
                const current = isCurrent(pathname, item.to, root);
                const Icon = item.icon;
                return (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      aria-current={current ? "page" : undefined}
                      aria-describedby={waitingId("rail", item)}
                      className={cn(
                        "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-foreground hover:bg-muted",
                        current && "bg-brand/10 font-semibold hover:bg-brand/10",
                      )}
                    >
                      <Icon
                        aria-hidden="true"
                        className="size-[18px] shrink-0 text-muted-foreground"
                      />
                      {item.label}
                      <Waiting place="rail" item={item} className="ml-auto" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}

function TabBar({
  navLabel,
  tabs,
  rest,
  groups,
  root,
  pathname,
}: {
  navLabel: string;
  tabs: ReadonlyArray<PortalNavItem>;
  rest: ReadonlyArray<PortalNavItem>;
  groups: Readonly<Record<string, string>>;
  root: string;
  pathname: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const moreCurrent = rest.some((item) => isCurrent(pathname, item.to, root));
  useEffect(() => setOpen(false), [pathname]);
  const slot =
    "relative flex min-h-16 flex-col items-center justify-center gap-0.5 px-1 pt-1.5 pb-1 text-xs";
  const pill = "grid h-7 w-14 place-items-center rounded-full transition-colors";
  // A waiting count sits on the icon pill's upper-right corner, ringed off in the leaf.
  const badge = "absolute top-0.5 left-[calc(50%+0.5rem)] ring-2 ring-surface";
  // More shows what waits among its destinations, like a closed rail group.
  const more = { to: "more", count: rest.reduce((sum, item) => sum + (item.count ?? 0), 0) };
  return (
    <>
      <nav
        aria-label={navLabel}
        className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)]"
      >
        <ul
          className="mx-auto grid max-w-lg"
          style={{
            gridTemplateColumns: `repeat(${tabs.length + (rest.length ? 1 : 0)}, minmax(0, 1fr))`,
          }}
        >
          {tabs.map((item) => {
            const current = isCurrent(pathname, item.to, root);
            const Icon = item.icon;
            return (
              <li key={item.to}>
                <Link
                  to={item.to}
                  aria-current={current ? "page" : undefined}
                  aria-describedby={waitingId("tab", item)}
                  className={cn(
                    slot,
                    current ? "font-semibold text-foreground" : "text-muted-foreground",
                  )}
                >
                  <span aria-hidden="true" className={cn(pill, current && "bg-brand/15")}>
                    <Icon className="size-5" />
                  </span>
                  <span className="max-w-full truncate">{item.label}</span>
                  <Waiting place="tab" item={item} className={badge} />
                </Link>
              </li>
            );
          })}
          {rest.length ? (
            <li>
              <button
                type="button"
                aria-haspopup="dialog"
                aria-expanded={open}
                aria-describedby={waitingId("tab", more)}
                onClick={() => setOpen(true)}
                className={cn(
                  slot,
                  "w-full",
                  moreCurrent ? "font-semibold text-foreground" : "text-muted-foreground",
                )}
              >
                <span aria-hidden="true" className={cn(pill, moreCurrent && "bg-brand/15")}>
                  <Ellipsis className="size-5" />
                </span>
                {t("portalFrame.more")}
                <Waiting place="tab" item={more} className={badge} />
              </button>
            </li>
          ) : null}
        </ul>
      </nav>
      {open ? (
        <MoreSheet
          items={rest}
          groups={groups}
          root={root}
          pathname={pathname}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}

function MoreSheet({
  items,
  groups,
  root,
  pathname,
  onClose,
}: {
  items: ReadonlyArray<PortalNavItem>;
  groups: Readonly<Record<string, string>>;
  root: string;
  pathname: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    // Mounted only while open; a bottom sheet that slides up from the tab bar.
    <dialog
      ref={dialog}
      aria-labelledby="more-sheet-h"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="m-0 mt-auto max-h-[85dvh] w-full max-w-none overflow-hidden rounded-t-xl border-t border-border bg-surface p-0 text-foreground transition-transform duration-200 ease-out backdrop:bg-black/40 open:flex open:flex-col starting:translate-y-full"
    >
      <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-3">
        <h2 id="more-sheet-h" className="text-base font-semibold">
          {t("portalFrame.more")}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("portalFrame.close")}
          className="-mr-2 grid size-10 place-items-center rounded-md hover:bg-muted"
        >
          <X aria-hidden="true" className="size-5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-[calc(env(safe-area-inset-bottom)+3.5rem)] [mask-image:linear-gradient(to_bottom,black_calc(100%-3.5rem),transparent)]">
        {groupItems(items).map(([group, list]) => (
          <section key={group || "top"} aria-labelledby={group ? `more-${group}` : undefined}>
            {group ? (
              <h3
                id={`more-${group}`}
                className="px-5 pt-4 pb-1 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
              >
                {groups[group] ?? group}
              </h3>
            ) : null}
            <ul>
              {list.map((item) => {
                const current = isCurrent(pathname, item.to, root);
                const Icon = item.icon;
                return (
                  <li key={item.to} className="border-b border-rule last:border-b-0">
                    <Link
                      to={item.to}
                      aria-current={current ? "page" : undefined}
                      aria-describedby={waitingId("sheet", item)}
                      onClick={onClose}
                      className={cn(
                        "flex min-h-12 items-center gap-3 px-5 text-sm hover:bg-muted",
                        current && "font-semibold",
                      )}
                    >
                      <Icon aria-hidden="true" className="size-5 shrink-0 text-muted-foreground" />
                      {item.label}
                      <Waiting place="sheet" item={item} className="ml-auto" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </dialog>
  );
}

function waitingId(place: string, item: { to: string; count?: number }): string | undefined {
  return item.count ? `waiting-${place}-${item.to.replace(/\W+/g, "-")}` : undefined;
}

/** A destination's waiting count: the margin-red pill for the eye, and the same count in
 * words as the link's description (hidden, so the destination's name stays its label). */
function Waiting({
  place,
  item,
  className,
}: {
  place: string;
  item: { to: string; count?: number };
  className?: string;
}) {
  const { t } = useTranslation();
  const id = waitingId(place, item);
  if (!id || !item.count) return null;
  return (
    <>
      <CountPill count={item.count} className={className} />
      <span id={id} hidden>
        {t("nav.waiting", { count: item.count })}
      </span>
    </>
  );
}

function groupItems(
  items: ReadonlyArray<PortalNavItem>,
): Array<[string, ReadonlyArray<PortalNavItem>]> {
  const out = new Map<string, PortalNavItem[]>();
  for (const item of items) {
    const key = item.group ?? "";
    out.set(key, [...(out.get(key) ?? []), item]);
  }
  return [...out.entries()];
}

function AccountMenu({ person, onSignOut }: { person: string; onSignOut: () => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
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
  const initials = person
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((value) => !value)}
        className="grid size-10 place-items-center rounded-full hover:bg-muted"
      >
        <span
          aria-hidden="true"
          className="grid size-8 place-items-center rounded-full border border-border bg-background text-xs font-semibold"
        >
          {initials || "?"}
        </span>
        <span className="sr-only">{t("portalFrame.account", { name: person })}</span>
      </button>
      {open ? (
        <div className="absolute right-0 z-40 mt-1 w-60 rounded-lg border border-border bg-surface p-1 text-sm shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)]">
          <p className="truncate px-3 py-2 text-muted-foreground">{person}</p>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-md px-3 py-2.5 text-left hover:bg-muted"
            onClick={onSignOut}
          >
            <LogOut aria-hidden="true" className="size-4 text-muted-foreground" />
            {t("portal.signOut")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
