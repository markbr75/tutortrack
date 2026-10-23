import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { useMutation } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { api } from "../api";

/** Up to two initials for the avatar disc ("Ada Lovelace" → "AL", "ops@tutortrack.app" → "O"). */
function initialsOf(name: string): string {
  const words = name.includes("@") ? [name] : name.split(/\s+/);
  return words
    .map((part) => part[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

/** A row in the account menu: a link or button styled like the menu's own items. */
export const accountMenuItem = "block w-full rounded-md px-3 py-2 text-left hover:bg-muted";

/**
 * The top bar's account menu (admin app and staff console): the signed-in person's bookcloth
 * disc opens a small menu with their name, any extra items, then Sign out. Escape and a click
 * outside close it.
 */
export function AccountMenu({
  name,
  children,
  afterSignOut = "/login",
}: {
  /** The signed-in person's name, or their email when there is no name. */
  name: string;
  /** Items between the name and Sign out; each receives `close` to shut the menu. */
  children?: (close: () => void) => ReactNode;
  /** Where to go once signed out. */
  afterSignOut?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const logout = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/auth/logout")),
    onSettled: () => window.location.assign(afterSignOut),
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
  const close = () => setOpen(false);
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
          {initialsOf(name) || "?"}
        </span>
        <span className="sr-only">{t("nav.userMenu", { name })}</span>
        <ChevronDown aria-hidden="true" className="size-4 text-muted-foreground" />
      </button>
      {open ? (
        <div className="absolute right-0 z-30 mt-2 w-56 rounded-lg border border-border bg-surface p-1 text-sm shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)]">
          <p className="truncate px-3 py-2 text-muted-foreground">{name}</p>
          {children?.(close)}
          <button
            type="button"
            className={accountMenuItem}
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
          >
            {t("nav.signOut")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
