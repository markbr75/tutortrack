import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Button,
  PageHeader,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { RecordHeader } from "../components/RecordHeader";

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
  const rows = list.data?.results ?? [];
  return (
    <div className="max-w-5xl">
      <PageHeader title={t("supportInbox.title")} />
      <form
        role="search"
        aria-label={t("supportInbox.title")}
        className="mb-4 flex flex-wrap items-center gap-2"
        onSubmit={(e) => e.preventDefault()}
      >
        <div className="min-w-56 flex-1">
          <TextField
            type="search"
            label={t("supportInbox.search")}
            hideLabel
            size="sm"
            placeholder={t("supportInbox.search")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <SelectField
          label={t("supportInbox.status")}
          hideLabel
          size="sm"
          value={status}
          onChange={(e) => setStatus(e.target.value as Status)}
          options={(["open", "unread", "answered", "closed", ""] as const).map((value) => ({
            value,
            label: t(`supportInbox.filters.${value || "all"}`),
          }))}
        />
      </form>
      <RuledPanel label={t("supportInbox.title")} flush>
        {list.isPending ? (
          <div className="px-5 py-4">
            <Spinner label={t("grid.loading")} />
          </div>
        ) : rows.length === 0 ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">{t("supportInbox.empty")}</p>
        ) : (
          <PanelRows>
            {rows.map((row) => (
              <PanelRow key={row.id} className="relative hover:bg-muted/60">
                <Link
                  to="/platform/support/$id"
                  params={{ id: row.id }}
                  className={`${row.support_unread ? "font-semibold" : "font-medium"} underline-offset-2 after:absolute after:inset-0 hover:underline`}
                >
                  {row.subject}
                </Link>
                <p className="truncate text-xs text-muted-foreground tabular-nums">
                  {row.support_unread ? (
                    <span className="font-semibold text-margin">{t("supportInbox.unread")} · </span>
                  ) : null}
                  {[
                    row.organisation_name,
                    row.opened_by_name || "–",
                    t(`supportInbox.statuses.${row.status}`),
                    formatDateTime(row.last_message_at, i18n.language),
                    row.assignee_name
                      ? t("supportInbox.assignedTo", { name: row.assignee_name })
                      : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </PanelRow>
            ))}
          </PanelRows>
        )}
      </RuledPanel>
    </div>
  );
}

/** One conversation: the record header, the messages as a ruled list, then the reply. */
export function SupportConversationPage({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
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
    <div className="max-w-3xl">
      <RecordHeader
        back={<Link to="/platform/support">{t("supportInbox.back")}</Link>}
        title={data.subject}
        description={
          <>
            <Link
              to="/platform/tenants/$id"
              params={{ id: data.organisation_id }}
              className="text-link underline-offset-2 hover:underline"
            >
              {data.organisation_name}
            </Link>
            {[data.opened_by_name || "–", t(`supportInbox.statuses.${data.status}`), data.page]
              .filter(Boolean)
              .map((part) => ` · ${part}`)
              .join("")}
          </>
        }
        actions={
          <>
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
          </>
        }
      />
      <RuledPanel label={t("supportInbox.messages")} flush>
        <ol aria-label={t("supportInbox.messages")} className="divide-y divide-rule">
          {data.messages.map((message) => (
            <li key={message.id} className="px-5 py-3 text-sm">
              <p className="text-xs text-muted-foreground tabular-nums">
                <span
                  className={
                    message.from_support
                      ? "font-semibold text-foreground"
                      : "font-medium text-foreground"
                  }
                >
                  {message.author_name || "–"}
                  {message.from_support ? ` (${t("supportInbox.support")})` : ""}
                </span>{" "}
                · {formatDateTime(message.created_at, i18n.language)}
              </p>
              <p className="mt-0.5 whitespace-pre-wrap">{message.body}</p>
            </li>
          ))}
        </ol>
        <form
          className="border-t border-border"
          onSubmit={(e) => {
            e.preventDefault();
            if (reply.trim()) send.mutate();
          }}
        >
          <div className="px-5 py-4">
            <TextAreaField
              label={t("supportInbox.reply")}
              rows={4}
              maxLength={5000}
              value={reply}
              onChange={(e) => setReply(e.target.value)}
            />
          </div>
          <PanelFooter>
            <Button type="submit" size="sm" loading={send.isPending} disabled={!reply.trim()}>
              {t("supportInbox.send")}
            </Button>
          </PanelFooter>
        </form>
      </RuledPanel>
    </div>
  );
}
