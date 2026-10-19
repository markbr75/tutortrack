import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
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
            className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-margin px-1 text-center text-[11px] leading-4 font-semibold text-margin-foreground"
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
          className="absolute right-0 z-30 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-surface p-3 shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)]"
        >
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">{t("comms.notifications")}</h2>
            {unread ? (
              <Button size="sm" variant="ghost" onClick={() => read.mutate()}>
                {t("comms.markAllRead")}
              </Button>
            ) : null}
          </div>
          <ul className="max-h-96 space-y-2 overflow-y-auto">
            {(list.data?.results ?? []).map((n) => (
              <li key={n.id} className={n.read_at ? "text-muted-foreground" : ""}>
                {n.link ? (
                  <Link
                    to={n.link}
                    className="text-sm font-medium underline-offset-2 hover:underline"
                    onClick={() => setOpen(false)}
                  >
                    {n.title}
                  </Link>
                ) : (
                  <p className="text-sm font-medium">{n.title}</p>
                )}
                {n.body ? <p className="text-xs">{n.body}</p> : null}
                <p className="text-xs text-muted-foreground">
                  {formatDateTime(n.created_at, i18n.language)}
                </p>
              </li>
            ))}
            {list.data && !list.data.results.length ? (
              <li className="text-sm text-muted-foreground">{t("comms.noNotifications")}</li>
            ) : null}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
