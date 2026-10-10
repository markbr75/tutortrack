import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

/** Outbox, dead letters, queues, webhook backlogs and status notices (E30 T04/T06). */
export function OperationsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const ops = useQuery({
    queryKey: ["platform", "operations"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/operations")),
    refetchInterval: 30_000,
  });
  const dead = useQuery({
    queryKey: ["platform", "dead-letters"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/dead-letters")),
  });
  const replay = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/platform/dead-letters/replay", { body: { ids: selected } })),
    onSuccess: () => {
      setSelected([]);
      void queryClient.invalidateQueries({ queryKey: ["platform"] });
    },
  });
  const figures = ops.data
    ? ([
        ["outboxPending", ops.data.outbox_pending],
        ["outboxLag", ops.data.outbox_lag_seconds],
        ["deadLetters", ops.data.dead_letters],
        ["paymentWebhooks", ops.data.payment_webhooks_unprocessed],
        ["billingWebhooks", ops.data.billing_webhooks_unprocessed],
        ...Object.entries(ops.data.queues).map(([q, n]) => [`queue:${q}`, n] as const),
      ] as const)
    : [];
  return (
    <div className="max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold">{t("platform.nav.operations")}</h1>
      {ops.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {figures.map(([label, value]) => (
          <div key={label} className="rounded-md border border-border p-3">
            <dt className="text-sm text-muted-foreground">
              {label.startsWith("queue:")
                ? t("platform.ops.queue", { name: label.slice(6) })
                : t(`platform.ops.${label}`)}
            </dt>
            <dd className="text-xl font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t("platform.deadLetters")}</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th scope="col">
                  <span className="sr-only">{t("platform.select")}</span>
                </th>
                <th scope="col">{t("platform.event")}</th>
                <th scope="col">{t("platform.organisation")}</th>
                <th scope="col">{t("platform.failedAt")}</th>
                <th scope="col">{t("platform.error")}</th>
              </tr>
            </thead>
            <tbody>
              {dead.data?.results.map((row) => (
                <tr key={row.id} className="border-t border-border align-top">
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t("platform.selectEvent", { type: row.event_type })}
                      checked={selected.includes(row.id)}
                      onChange={(e) =>
                        setSelected((s) =>
                          e.target.checked ? [...s, row.id] : s.filter((x) => x !== row.id),
                        )
                      }
                    />
                  </td>
                  <td>{row.event_type}</td>
                  <td>{row.organisation_name ?? "–"}</td>
                  <td>{formatDateTime(row.dead_lettered_at)}</td>
                  <td className="max-w-md break-words">{row.last_error}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Button
          size="sm"
          disabled={!selected.length}
          loading={replay.isPending}
          onClick={() => replay.mutate()}
        >
          {t("platform.replay", { count: selected.length })}
        </Button>
      </section>
      <Notices />
    </div>
  );
}

function Notices() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [severity, setSeverity] = useState<"info" | "warning" | "outage">("warning");
  const notices = useQuery({
    queryKey: ["platform", "notices"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/notices")),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["platform", "notices"] });
  const post = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/platform/notices", {
          body: { message, severity, starts_at: new Date().toISOString(), ends_at: null },
        }),
      ),
    onSuccess: () => {
      setMessage("");
      refresh();
    },
  });
  const end = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.PATCH("/api/v1/platform/notices/{id}", {
          params: { path: { id } },
          body: { ends_at: new Date().toISOString() },
        }),
      ),
    onSuccess: refresh,
  });
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{t("platform.notices")}</h2>
      <ul className="text-sm">
        {notices.data?.map((n) => {
          const live = !n.ends_at || new Date(n.ends_at) > new Date();
          return (
            <li key={n.id} className="flex items-center justify-between gap-2 py-1">
              <span>
                [{n.severity}] {n.message} · {formatDateTime(n.starts_at)}
              </span>
              {live ? (
                <Button size="sm" variant="ghost" onClick={() => end.mutate(n.id)}>
                  {t("platform.endNotice")}
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          post.mutate();
        }}
      >
        <TextField
          label={t("platform.noticeMessage")}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">{t("platform.severity")}</span>
          <select
            className="h-10 rounded-md border border-border bg-background px-2"
            value={severity}
            onChange={(e) => setSeverity(e.target.value as typeof severity)}
          >
            {(["info", "warning", "outage"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`platform.severities.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" size="sm" loading={post.isPending}>
          {t("platform.postNotice")}
        </Button>
      </form>
      {post.error ? <Alert tone="danger">{post.error.message}</Alert> : null}
    </section>
  );
}
