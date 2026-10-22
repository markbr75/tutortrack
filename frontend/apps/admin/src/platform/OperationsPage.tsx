import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FigureStrip,
  PageHeader,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

/** Outbox, dead letters, queues, webhook backlogs and status notices (E30 T04/T06). */
export function OperationsPage() {
  const { t, i18n } = useTranslation();
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
  const rows = dead.data?.results ?? [];
  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader title={t("platform.nav.operations")} />
      {ops.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {figures.length ? (
        <FigureStrip
          label={t("platform.nav.operations")}
          columns={3}
          figures={figures.map(([label, value]) => ({
            key: label,
            label: label.startsWith("queue:")
              ? t("platform.ops.queue", { name: label.slice(6) })
              : t(`platform.ops.${label}`),
            value: value.toLocaleString(i18n.language),
            // Dead letters wait on us; everything else is a level, not a fault.
            tone: label === "deadLetters" && Number(value) > 0 ? ("margin" as const) : undefined,
          }))}
        />
      ) : null}
      <RuledPanel
        title={t("platform.deadLetters")}
        rule={rows.length ? "margin" : "border"}
        aside={
          rows.length ? (
            <span className="font-semibold text-margin tabular-nums">
              {t("designS11.platform.waiting", { count: rows.length })}
            </span>
          ) : null
        }
        flush
        footer={
          rows.length ? (
            <Button
              size="sm"
              disabled={!selected.length}
              loading={replay.isPending}
              onClick={() => replay.mutate()}
            >
              {t("platform.replay", { count: selected.length })}
            </Button>
          ) : null
        }
      >
        <RuledTable
          caption={t("platform.deadLetters")}
          loading={dead.isPending}
          loadingLabel={t("grid.loading")}
          empty={dead.data && !rows.length ? t("designS11.platform.noDeadLetters") : undefined}
          columns={[
            { header: t("platform.select"), hidden: true, width: "w-10" },
            { header: t("platform.event") },
            { header: t("platform.organisation") },
            { header: t("platform.failedAt") },
            { header: t("platform.error") },
          ]}
        >
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="align-top">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4"
                  aria-label={t("platform.selectEvent", { type: row.event_type })}
                  checked={selected.includes(row.id)}
                  onChange={(e) =>
                    setSelected((s) =>
                      e.target.checked ? [...s, row.id] : s.filter((x) => x !== row.id),
                    )
                  }
                />
              </td>
              <td className="font-mono text-xs leading-5">{row.event_type}</td>
              <td>{row.organisation_name ?? "–"}</td>
              <td className="whitespace-nowrap tabular-nums">
                {formatDateTime(row.dead_lettered_at, i18n.language)}
              </td>
              <td className="max-w-md min-w-56 break-words text-danger">{row.last_error}</td>
            </tr>
          ))}
        </RuledTable>
      </RuledPanel>
      <Notices />
    </div>
  );
}

/** Status notices shown to every organisation: what is live, then a new one. */
function Notices() {
  const { t, i18n } = useTranslation();
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
    <RuledPanel title={t("platform.notices")} flush>
      {notices.data?.length ? (
        <PanelRows>
          {notices.data.map((n) => {
            const live = !n.ends_at || new Date(n.ends_at) > new Date();
            return (
              <PanelRow key={n.id} className="flex flex-wrap items-start justify-between gap-2">
                <span className="min-w-0">
                  <span className="break-words">{n.message}</span>
                  <span className="block text-xs text-muted-foreground tabular-nums">
                    {t(`platform.severities.${n.severity}`)} ·{" "}
                    {formatDateTime(n.starts_at, i18n.language)}
                    {live ? "" : ` · ${t("designS11.platform.ended")}`}
                  </span>
                </span>
                {live ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    onClick={() => end.mutate(n.id)}
                  >
                    {t("platform.endNotice")}
                  </Button>
                ) : null}
              </PanelRow>
            );
          })}
        </PanelRows>
      ) : notices.data ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">
          {t("designS11.platform.noNotices")}
        </p>
      ) : null}
      <form
        className="border-t border-border"
        onSubmit={(e) => {
          e.preventDefault();
          post.mutate();
        }}
      >
        <div className="flex flex-wrap items-end gap-x-4 gap-y-3 px-5 py-4">
          <div className="min-w-56 flex-1">
            <TextField
              label={t("platform.noticeMessage")}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
          </div>
          <SelectField
            label={t("platform.severity")}
            value={severity}
            onChange={(e) => setSeverity(e.target.value as typeof severity)}
            options={(["info", "warning", "outage"] as const).map((s) => ({
              value: s,
              label: t(`platform.severities.${s}`),
            }))}
          />
        </div>
        {post.error ? (
          <div className="px-5 pb-4">
            <Alert tone="danger">{post.error.message}</Alert>
          </div>
        ) : null}
        <PanelFooter>
          <Button type="submit" size="sm" loading={post.isPending}>
            {t("platform.postNotice")}
          </Button>
        </PanelFooter>
      </form>
    </RuledPanel>
  );
}
