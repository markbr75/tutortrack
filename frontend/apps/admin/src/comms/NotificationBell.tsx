import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Bell } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { useNotificationStream } from "./useNotificationStream";

/** The in-app notification bell (FR-13-8). Updates live over Server-Sent Events (G4) and
 * falls back to polling the unread count every 30 seconds. */
export function NotificationBell() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const live = useNotificationStream();
  const count = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: async () => unwrap(await api.GET("/api/v1/notifications/unread-count")),
    refetchInterval: live ? false : 30_000,
  });
  const list = useQuery({
    queryKey: ["notifications", "list"],
    enabled: open,
    queryFn: async () => unwrap(await api.GET("/api/v1/notifications")),
  });
  const read = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/notifications/read", { body: {} })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const unread = count.data?.unread ?? 0;

  return (
    <div className="relative">
      <button
        type="button"
        className="relative grid size-9 place-items-center rounded-md hover:bg-muted"
        aria-expanded={open}
        aria-controls="notification-panel"
        onClick={() => setOpen((v) => !v)}
      >
        <Bell aria-hidden="true" className="size-5" strokeWidth={1.75} />
        <span className="sr-only">{t("comms.bell", { count: unread })}</span>
        {unread ? (
          <span
            aria-hidden="true"
            className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-margin px-1 text-center text-xs leading-4 font-semibold text-margin-foreground"
          >
            {unread > 99 ? "99+" : unread}
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          id="notification-panel"
          role="region"
          aria-label={t("comms.notifications")}
          className="absolute right-0 z-30 mt-2 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-md border border-border bg-surface shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)]"
        >
          <div className="flex min-h-11 items-center justify-between gap-2 border-b border-border py-1.5 pr-2 pl-4">
            <h2 className="text-base font-semibold">{t("comms.notifications")}</h2>
            {unread ? (
              <Button size="sm" variant="ghost" onClick={() => read.mutate()}>
                {t("comms.markAllRead")}
              </Button>
            ) : null}
          </div>
          {list.isPending ? (
            <div className="px-4 py-3">
              <Spinner label={t("grid.loading")} />
            </div>
          ) : (
            <ul className="max-h-96 divide-y divide-rule overflow-y-auto overscroll-contain">
              {(list.data?.results ?? []).map((n) => (
                <li key={n.id} className="relative px-4 py-2.5 text-sm hover:bg-muted/60">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="flex min-w-0 items-baseline gap-2">
                      {n.read_at ? null : (
                        <>
                          <span
                            aria-hidden="true"
                            className="size-1.5 shrink-0 translate-y-[-1px] rounded-full bg-margin"
                          />
                          <span className="sr-only">{t("designS8.comms.new")}</span>
                        </>
                      )}
                      {n.link ? (
                        <Link
                          to={n.link}
                          className={`min-w-0 underline-offset-2 after:absolute after:inset-0 hover:underline ${n.read_at ? "" : "font-semibold"}`}
                          onClick={() => setOpen(false)}
                        >
                          {n.title}
                        </Link>
                      ) : (
                        <span className={`min-w-0 ${n.read_at ? "" : "font-semibold"}`}>
                          {n.title}
                        </span>
                      )}
                    </span>
                    <time
                      dateTime={n.created_at}
                      className="shrink-0 text-xs whitespace-nowrap text-muted-foreground"
                    >
                      {formatDateTime(n.created_at, i18n.language, undefined, {
                        dateStyle: "short",
                        timeStyle: "short",
                      })}
                    </time>
                  </div>
                  {n.body ? (
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{n.body}</p>
                  ) : null}
                </li>
              ))}
              {list.data && !list.data.results.length ? (
                <li className="px-4 py-4 text-sm text-muted-foreground">
                  {t("comms.noNotifications")}
                </li>
              ) : null}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
