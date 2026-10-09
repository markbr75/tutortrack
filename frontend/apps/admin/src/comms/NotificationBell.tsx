import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";

/** The in-app notification bell (FR-13-8). Polls for the unread count. */
export function NotificationBell() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const count = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: async () => unwrap(await api.GET("/api/v1/notifications/unread-count")),
    refetchInterval: 30_000,
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
        className="rounded-md px-2 py-1 text-sm hover:bg-muted"
        aria-expanded={open}
        aria-controls="notification-panel"
        onClick={() => setOpen((v) => !v)}
      >
        {t("comms.bell", { count: unread })}
      </button>
      {open ? (
        <div
          id="notification-panel"
          role="region"
          aria-label={t("comms.notifications")}
          className="absolute z-20 mt-1 w-80 rounded-md border border-border bg-background p-3 shadow-lg"
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
