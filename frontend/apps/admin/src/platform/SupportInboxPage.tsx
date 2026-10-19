import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";

import { api } from "../api";

type Status = "" | "open" | "answered" | "closed" | "unread";

/** Support conversations from every organisation (E30 FR-30-5, console side). */
export function SupportInboxPage() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState<Status>("open");
  const [search, setSearch] = useState("");
  const list = useQuery({
    queryKey: ["platform", "support", status, search],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/platform/support", {
          params: { query: { status: status || undefined, search: search || undefined } },
        }),
      ),
  });
  return (
    <div className="max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold">{t("supportInbox.title")}</h1>
      <div className="flex flex-wrap gap-4">
        <div className="w-48">
          <SelectField
            label={t("supportInbox.status")}
            value={status}
            onChange={(e) => setStatus(e.target.value as Status)}
            options={(["open", "unread", "answered", "closed", ""] as const).map((value) => ({
              value,
              label: t(`supportInbox.filters.${value || "all"}`),
            }))}
          />
        </div>
        <div className="w-64">
          <TextField
            type="search"
            label={t("supportInbox.search")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      {list.isPending ? <Spinner label={t("grid.loading")} /> : null}
      <ul className="divide-y divide-border rounded-md border border-border">
        {(list.data?.results ?? []).map((row) => (
          <li key={row.id} className="p-3">
            <Link
              to="/platform/support/$id"
              params={{ id: row.id }}
              className="font-medium underline"
            >
              {row.subject}
            </Link>
            {row.support_unread ? (
              <span className="ml-2 rounded bg-brand px-1 text-xs text-brand-foreground">
                {t("supportInbox.unread")}
              </span>
            ) : null}
            <p className="text-xs text-muted-foreground">
              {row.organisation_name} · {row.opened_by_name || "—"} ·{" "}
              {t(`supportInbox.statuses.${row.status}`)} ·{" "}
              {formatDateTime(row.last_message_at, i18n.language)}
              {row.assignee_name
                ? ` · ${t("supportInbox.assignedTo", { name: row.assignee_name })}`
                : ""}
            </p>
          </li>
        ))}
        {list.data && list.data.results.length === 0 ? (
          <li className="p-3 text-sm text-muted-foreground">{t("supportInbox.empty")}</li>
        ) : null}
      </ul>
    </div>
  );
}

export function SupportConversationPage({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const replyId = useId();
  const [reply, setReply] = useState("");
  const key = ["platform", "support", "conversation", id];
  const conversation = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/platform/support/{id}", { params: { path: { id } } })),
  });
  const done = (data: unknown) => {
    queryClient.setQueryData(key, data);
    void queryClient.invalidateQueries({ queryKey: ["platform", "support"] });
  };
  const send = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/platform/support/{id}/reply", {
          params: { path: { id } },
          body: { body: reply },
        }),
      ),
    onSuccess: (data) => {
      setReply("");
      done(data);
    },
  });
  const close = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/platform/support/{id}/close", { params: { path: { id } } })),
    onSuccess: done,
  });
  const assign = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/platform/support/{id}/assign", { params: { path: { id } } })),
    onSuccess: done,
  });
  const data = conversation.data;
  if (!data) return <Spinner label={t("grid.loading")} />;
  return (
    <div className="max-w-3xl space-y-4">
      <Link to="/platform/support" className="text-sm underline">
        {t("supportInbox.back")}
      </Link>
      <h1 className="text-2xl font-semibold">{data.subject}</h1>
      <p className="text-sm text-muted-foreground">
        <Link
          to="/platform/tenants/$id"
          params={{ id: data.organisation_id }}
          className="underline"
        >
          {data.organisation_name}
        </Link>{" "}
        · {data.opened_by_name || "—"} · {t(`supportInbox.statuses.${data.status}`)}
        {data.page ? ` · ${data.page}` : ""}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="secondary"
          loading={assign.isPending}
          onClick={() => assign.mutate()}
        >
          {t("supportInbox.assignToMe")}
        </Button>
        {data.status !== "closed" ? (
          <Button
            size="sm"
            variant="secondary"
            loading={close.isPending}
            onClick={() => close.mutate()}
          >
            {t("supportInbox.close")}
          </Button>
        ) : null}
      </div>
      <ol className="space-y-2" aria-label={t("supportInbox.messages")}>
        {data.messages.map((message) => (
          <li
            key={message.id}
            className={
              message.from_support
                ? "rounded-md border border-border bg-muted p-3"
                : "rounded-md border border-border p-3"
            }
          >
            <p className="text-xs text-muted-foreground">
              {message.author_name || "—"}
              {message.from_support ? ` (${t("supportInbox.support")})` : ""} ·{" "}
              {formatDateTime(message.created_at, i18n.language)}
            </p>
            <p className="whitespace-pre-wrap text-sm">{message.body}</p>
          </li>
        ))}
      </ol>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (reply.trim()) send.mutate();
        }}
      >
        <label htmlFor={replyId} className="text-sm font-medium">
          {t("supportInbox.reply")}
        </label>
        <textarea
          id={replyId}
          rows={4}
          maxLength={5000}
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        />
        <Button type="submit" loading={send.isPending} disabled={!reply.trim()}>
          {t("supportInbox.send")}
        </Button>
      </form>
    </div>
  );
}
