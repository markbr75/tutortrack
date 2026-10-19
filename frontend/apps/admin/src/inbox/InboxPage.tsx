import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type FormEvent } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { AiReplySuggest, AiThreadTools } from "../ai/AiWidgets";

type Thread = components["schemas"]["Thread"];
type Box = "open" | "mine" | "unassigned" | "snoozed" | "closed" | "flagged";
type ReplyChannel = "email" | "sms" | "whatsapp" | "chat";

const BOXES: Box[] = ["open", "mine", "unassigned", "snoozed", "closed", "flagged"];
const POLL_MS = 30_000;

function ThreadList({
  box,
  selected,
  onSelect,
}: {
  box: Box;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const [q, setQ] = useState("");
  const threads = useQuery({
    queryKey: ["threads", box, q],
    refetchInterval: POLL_MS,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/threads", {
          params: { query: { box, q: q || undefined, page_size: 100 } },
        }),
      ),
  });
  return (
    <div className="space-y-2">
      <TextField
        label={t("inbox.search")}
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {threads.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : !threads.data?.results.length ? (
        <p className="text-sm text-muted-foreground">{t("inbox.empty")}</p>
      ) : (
        <ul
          className="divide-y divide-border rounded-md border border-border"
          aria-label={t("inbox.conversations")}
        >
          {threads.data.results.map((thread) => (
            <li key={thread.id}>
              <button
                type="button"
                aria-current={selected === thread.id ? "true" : undefined}
                onClick={() => onSelect(thread.id)}
                className="w-full p-2 text-left text-sm hover:bg-muted aria-[current=true]:bg-muted"
              >
                <span className="flex justify-between gap-2">
                  <span className="font-medium">
                    {thread.party || t("inbox.unknown")}
                    {thread.unread ? (
                      <span className="ml-1 rounded bg-primary px-1 text-xs text-primary-foreground">
                        {t("inbox.unread", { count: thread.unread })}
                      </span>
                    ) : null}
                  </span>
                  {thread.last_message_at ? (
                    <span className="text-xs text-muted-foreground">
                      {formatDateTime(thread.last_message_at, i18n.language)}
                    </span>
                  ) : null}
                </span>
                <span className="block truncate text-muted-foreground">
                  {thread.subject ? `${thread.subject} · ` : ""}
                  {thread.last_message_preview}
                </span>
                <span className="text-xs">
                  {t(`comms.channel.${thread.channel}`, { defaultValue: t("inbox.chat") })}
                  {thread.sla_breached ? ` · ${t("inbox.overdue")}` : ""}
                  {thread.flagged ? ` · ${t("inbox.flagged")}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Composer({ thread }: { thread: Thread }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const bodyId = useId();
  const [body, setBody] = useState("");
  const [channel, setChannel] = useState<ReplyChannel>((thread.channel as ReplyChannel) || "chat");
  const canned = useQuery({
    queryKey: ["canned-replies"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/canned-replies", { params: { query: { page_size: 100 } } })),
  });
  useEffect(
    () => setChannel((thread.channel as ReplyChannel) || "chat"),
    [thread.id, thread.channel],
  );
  const path = { params: { path: { id: thread.id } } };
  const sent = () => {
    setBody("");
    void queryClient.invalidateQueries({ queryKey: ["threads"] });
  };
  const reply = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/threads/{id}/messages", {
          ...path,
          body: { body, channel, subject: "" },
        }),
      ),
    onSuccess: sent,
  });
  const note = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/threads/{id}/notes", { ...path, body: { body } })),
    onSuccess: sent,
  });
  const errors = fieldErrors(reply.error ?? note.error);
  const channels: ReplyChannel[] =
    thread.kind === "other"
      ? thread.contact_email
        ? ["email"]
        : ["sms", "whatsapp"]
      : ["chat", "email", "sms", "whatsapp"];
  return (
    <form
      aria-label={t("inbox.reply")}
      className="space-y-2"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        reply.mutate();
      }}
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <SelectField
          label={t("inbox.via")}
          value={channel}
          error={errors.channel}
          onChange={(e) => setChannel(e.target.value as ReplyChannel)}
          options={channels.map((c) => ({
            value: c,
            label: c === "chat" ? t("inbox.chat") : t(`comms.channel.${c}`),
          }))}
        />
        <SelectField
          label={t("inbox.cannedReply")}
          value=""
          onChange={(e) => {
            const found = canned.data?.results.find((r) => r.id === e.target.value);
            if (found) setBody((current) => (current ? `${current}\n${found.body}` : found.body));
          }}
          options={[
            { value: "", label: t("inbox.insertCanned") },
            ...(canned.data?.results ?? []).map((r) => ({ value: r.id, label: r.title })),
          ]}
        />
      </div>
      {!thread.flagged ? (
        <AiReplySuggest threadId={thread.id} current={body} onSuggest={setBody} />
      ) : null}
      <label htmlFor={bodyId} className="text-sm font-medium">
        {t("inbox.message")}
      </label>
      <textarea
        id={bodyId}
        rows={4}
        value={body}
        aria-invalid={errors.body ? true : undefined}
        onChange={(e) => setBody(e.target.value)}
        className="w-full rounded-md border border-border bg-background p-2 text-sm"
      />
      {reply.error || note.error ? (
        <Alert tone="danger">
          {errors.channel ?? errors.body ?? (reply.error ?? note.error)?.message}
        </Alert>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={!body.trim() || reply.isPending}>
          {t("inbox.send")}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={!body.trim() || note.isPending}
          onClick={() => note.mutate()}
        >
          {t("inbox.addNote")}
        </Button>
      </div>
    </form>
  );
}

function Conversation({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canAssign = usePermission("comms.inbox.assign");
  const canReply = usePermission("comms.inbox.reply");
  const [until, setUntil] = useState("");
  const path = { params: { path: { id } } };
  const thread = useQuery({
    queryKey: ["threads", "detail", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/threads/{id}", path)),
  });
  const messages = useQuery({
    queryKey: ["threads", "messages", id],
    refetchInterval: POLL_MS,
    queryFn: async () => unwrap(await api.GET("/api/v1/threads/{id}/messages", path)),
  });
  const assignees = useQuery({
    queryKey: ["threads", "assignees"],
    enabled: canAssign,
    queryFn: async () => unwrap(await api.GET("/api/v1/threads/assignees")),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["threads"] });
  const assign = useMutation({
    mutationFn: async (assignee: string) =>
      unwrap(
        await api.POST("/api/v1/threads/{id}/assign", {
          ...path,
          body: { assignee: assignee || null },
        }),
      ),
    onSuccess: refresh,
  });
  const status = useMutation({
    mutationFn: async (action: "close" | "reopen" | "snooze") => {
      if (action === "snooze") {
        return unwrap(
          await api.POST("/api/v1/threads/{id}/snooze", {
            ...path,
            body: { until: new Date(until).toISOString() },
          }),
        );
      }
      if (action === "close") return unwrap(await api.POST("/api/v1/threads/{id}/close", path));
      return unwrap(await api.POST("/api/v1/threads/{id}/reopen", path));
    },
    onSuccess: refresh,
  });
  if (!thread.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const th = thread.data;
  return (
    <section aria-labelledby="thread-title" className="space-y-4">
      <header className="space-y-1">
        <h2 id="thread-title" className="text-lg font-semibold">
          {th.party || t("inbox.unknown")}
          {th.subject ? ` · ${th.subject}` : ""}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t(`inbox.kinds.${th.kind}`)} · {t(`inbox.statuses.${th.status}`)}
          {th.sla_due_at
            ? ` · ${t(th.sla_breached ? "inbox.slaBreached" : "inbox.slaDue", {
                when: formatDateTime(th.sla_due_at, i18n.language),
              })}`
            : ""}
        </p>
        {th.reply_address ? (
          <p className="text-xs text-muted-foreground">
            {t("inbox.replyAddress", { address: th.reply_address })}
          </p>
        ) : null}
      </header>
      {!th.flagged ? <AiThreadTools threadId={th.id} /> : null}
      {canAssign ? (
        <div className="flex flex-wrap items-end gap-2">
          <SelectField
            label={t("inbox.assignee")}
            value={th.assignee ?? ""}
            onChange={(e) => assign.mutate(e.target.value)}
            options={[
              { value: "", label: t("inbox.nobody") },
              ...(assignees.data ?? []).map((a) => ({ value: a.id, label: a.name })),
            ]}
          />
          <TextField
            label={t("inbox.snoozeUntil")}
            type="datetime-local"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
          />
          <Button variant="secondary" disabled={!until} onClick={() => status.mutate("snooze")}>
            {t("inbox.snooze")}
          </Button>
          {th.status === "closed" ? (
            <Button variant="secondary" onClick={() => status.mutate("reopen")}>
              {t("inbox.reopen")}
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => status.mutate("close")}>
              {t("inbox.close")}
            </Button>
          )}
        </div>
      ) : null}
      {status.error ? <Alert tone="danger">{status.error.message}</Alert> : null}
      <ol className="space-y-2" aria-label={t("inbox.messages")}>
        {(messages.data ?? []).map((m) => (
          <li
            key={m.id}
            className={
              m.direction === "internal"
                ? "rounded-md border border-warning/40 bg-warning/10 p-2 text-sm text-foreground"
                : m.direction === "outbound"
                  ? "ml-8 rounded-md bg-muted p-2 text-sm"
                  : "mr-8 rounded-md border border-border p-2 text-sm"
            }
          >
            <p className="text-xs text-muted-foreground">
              {m.author_name} · {formatDateTime(m.created_at, i18n.language)} ·{" "}
              {m.direction === "internal"
                ? t("inbox.internalNote")
                : m.channel === "chat"
                  ? t("inbox.chat")
                  : t(`comms.channel.${m.channel}`)}
              {m.delivery_status ? ` · ${m.delivery_status}` : ""}
            </p>
            <p className="whitespace-pre-wrap">{m.body}</p>
            {m.attachments.length ? (
              <ul className="text-xs">
                {m.attachments.map((a) => (
                  <li key={a.id}>📎 {a.filename}</li>
                ))}
              </ul>
            ) : null}
            {m.flags.length ? (
              <p className="text-xs font-medium text-danger">
                {t("inbox.flags", {
                  flags: m.flags.map((f) => t(`inbox.flag.${f}`)).join(", "),
                })}
              </p>
            ) : null}
          </li>
        ))}
      </ol>
      {canReply ? <Composer thread={th} /> : null}
    </section>
  );
}

/** The team inbox (E13-T11): email, text, WhatsApp and portal conversations with
 * assignment, snooze, internal notes, canned replies and a reply-time target. */
export function InboxPage() {
  const { t } = useTranslation();
  const params = new URLSearchParams(window.location.search);
  const [box, setBox] = useState<Box>("open");
  const [selected, setSelected] = useState<string | null>(params.get("thread"));
  const counts = useQuery({
    queryKey: ["threads", "counts"],
    refetchInterval: POLL_MS,
    queryFn: async () => unwrap(await api.GET("/api/v1/threads/counts")),
  });
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("inbox.title")}</h1>
      <nav aria-label={t("inbox.boxes")} className="flex flex-wrap gap-2">
        {BOXES.map((b) => (
          <Button
            key={b}
            size="sm"
            variant={box === b ? "primary" : "secondary"}
            aria-pressed={box === b}
            onClick={() => setBox(b)}
          >
            {t(`inbox.box.${b}`)}
            {counts.data && b in counts.data
              ? ` (${counts.data[b as keyof typeof counts.data]})`
              : ""}
          </Button>
        ))}
      </nav>
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <ThreadList box={box} selected={selected} onSelect={setSelected} />
        {selected ? (
          <Conversation id={selected} />
        ) : (
          <p className="text-sm text-muted-foreground">{t("inbox.pick")}</p>
        )}
      </div>
    </section>
  );
}
