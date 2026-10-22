import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PageHeader,
  PanelFooter,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Paperclip } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { AiReplySuggest, AiThreadTools } from "../ai/AiWidgets";
import { useIsPhone } from "../billing/useIsPhone";

type Thread = components["schemas"]["Thread"];
type Box = "open" | "mine" | "unassigned" | "snoozed" | "closed" | "flagged";
type ReplyChannel = "email" | "sms" | "whatsapp" | "chat";

const BOXES: Box[] = ["open", "mine", "unassigned", "snoozed", "closed", "flagged"];
/** Boxes whose count is work waiting on the team: shown as a margin-red count. */
const WAITING: Box[] = ["mine", "unassigned", "flagged"];
const POLL_MS = 30_000;

/** A margin-red count pill (hidden from assistive tech; the caller says it in words). */
function CountPill({ count }: { count: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-margin px-1.5 text-xs leading-4 font-semibold text-margin-foreground tabular-nums"
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}

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
    <div className="min-w-0 rounded-xl border border-border bg-surface lg:sticky lg:top-20">
      <div
        className="border-b border-border px-4 py-3"
        role="search"
        aria-label={t("inbox.search")}
      >
        <TextField
          label={t("inbox.search")}
          hideLabel
          size="sm"
          placeholder={t("inbox.search")}
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      {threads.isPending ? (
        <div className="px-4 py-3">
          <Spinner label={t("grid.loading")} />
        </div>
      ) : !threads.data?.results.length ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">{t("inbox.empty")}</p>
      ) : (
        <ul
          className="divide-y divide-rule overscroll-contain lg:max-h-[calc(100vh-15rem)] lg:overflow-y-auto"
          aria-label={t("inbox.conversations")}
        >
          {threads.data.results.map((thread) => (
            <li key={thread.id}>
              <button
                type="button"
                aria-current={selected === thread.id ? "true" : undefined}
                onClick={() => onSelect(thread.id)}
                className="block w-full px-4 py-2.5 text-left text-sm hover:bg-muted/60 aria-[current=true]:bg-muted"
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className={`truncate ${thread.unread ? "font-semibold" : "font-medium"}`}>
                      {thread.party || t("inbox.unknown")}
                    </span>
                    {thread.unread ? (
                      <>
                        <CountPill count={thread.unread} />
                        <span className="sr-only">
                          {" "}
                          {t("inbox.unread", { count: thread.unread })}
                        </span>
                      </>
                    ) : null}
                  </span>
                  {thread.last_message_at ? (
                    <time
                      dateTime={thread.last_message_at}
                      className="shrink-0 text-xs whitespace-nowrap text-muted-foreground"
                    >
                      {formatDateTime(thread.last_message_at, i18n.language)}
                    </time>
                  ) : null}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {thread.sla_breached ? (
                    <span className="font-semibold text-margin">{t("inbox.overdue")} · </span>
                  ) : null}
                  {thread.flagged ? (
                    <span className="font-medium text-foreground">{t("inbox.flagged")} · </span>
                  ) : null}
                  {thread.channel === "chat"
                    ? t("inbox.chat")
                    : t(`comms.channel.${thread.channel}`, { defaultValue: t("inbox.chat") })}
                  {thread.subject ? ` · ${thread.subject}` : ""}
                  {thread.last_message_preview ? ` · ${thread.last_message_preview}` : ""}
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
      className="border-t border-border"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        reply.mutate();
      }}
    >
      <div className="space-y-3 px-5 py-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <SelectField
            label={t("inbox.via")}
            size="sm"
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
            size="sm"
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
        <div className="flex flex-col gap-1">
          <label htmlFor={bodyId} className="text-sm font-medium">
            {t("inbox.message")}
          </label>
          <textarea
            id={bodyId}
            rows={4}
            value={body}
            aria-invalid={errors.body ? true : undefined}
            onChange={(e) => setBody(e.target.value)}
            className="w-full rounded-md border border-field bg-surface px-3 py-2 text-sm"
          />
        </div>
        {reply.error || note.error ? (
          <Alert tone="danger">
            {errors.channel ?? errors.body ?? (reply.error ?? note.error)?.message}
          </Alert>
        ) : null}
      </div>
      <PanelFooter className="justify-end">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={!body.trim()}
          loading={note.isPending}
          onClick={() => note.mutate()}
        >
          {t("inbox.addNote")}
        </Button>
        <Button type="submit" size="sm" disabled={!body.trim()} loading={reply.isPending}>
          {t("inbox.send")}
        </Button>
      </PanelFooter>
    </form>
  );
}

const inlineField = "h-9 rounded-md border border-field bg-surface px-3 text-sm";

function Conversation({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canAssign = usePermission("comms.inbox.assign");
  const canReply = usePermission("comms.inbox.reply");
  const [until, setUntil] = useState("");
  const assigneeId = useId();
  const untilId = useId();
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
  if (!thread.data)
    return (
      <div className="rounded-xl border border-border bg-surface px-5 py-4">
        <Spinner label={t("grid.loading")} />
      </div>
    );
  const th = thread.data;
  return (
    <section
      aria-labelledby="thread-title"
      className="min-w-0 rounded-xl border border-border bg-surface"
    >
      <header className="border-b border-border px-5 py-3.5">
        <h2 id="thread-title" className="text-base font-semibold">
          {th.party || t("inbox.unknown")}
          {th.subject ? ` · ${th.subject}` : ""}
        </h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {t(`inbox.kinds.${th.kind}`)} · {t(`inbox.statuses.${th.status}`)}
          {th.sla_due_at ? (
            <>
              {" · "}
              <span className={th.sla_breached ? "font-semibold text-margin" : undefined}>
                {t(th.sla_breached ? "inbox.slaBreached" : "inbox.slaDue", {
                  when: formatDateTime(th.sla_due_at, i18n.language),
                })}
              </span>
            </>
          ) : null}
        </p>
        {th.reply_address ? (
          <p className="mt-0.5 text-xs break-all text-muted-foreground">
            {t("inbox.replyAddress", { address: th.reply_address })}
          </p>
        ) : null}
      </header>
      {canAssign ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule px-5 py-3 text-sm">
          <span className="flex items-center gap-2">
            <label htmlFor={assigneeId} className="text-muted-foreground">
              {t("inbox.assignee")}
            </label>
            <select
              id={assigneeId}
              className={inlineField}
              value={th.assignee ?? ""}
              onChange={(e) => assign.mutate(e.target.value)}
            >
              <option value="">{t("inbox.nobody")}</option>
              {(assignees.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </span>
          <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto sm:flex-1">
            <span className="flex min-w-0 flex-1 flex-nowrap items-center gap-2">
              <label htmlFor={untilId} className="shrink-0 text-muted-foreground">
                {t("inbox.snoozeUntil")}
              </label>
              <input
                id={untilId}
                type="datetime-local"
                className={`${inlineField} w-full min-w-0 sm:max-w-56`}
                value={until}
                onChange={(e) => setUntil(e.target.value)}
              />
              <Button
                size="sm"
                variant="secondary"
                className="shrink-0"
                disabled={!until}
                onClick={() => status.mutate("snooze")}
              >
                {t("inbox.snooze")}
              </Button>
            </span>
            {th.status === "closed" ? (
              <Button
                size="sm"
                variant="secondary"
                className="shrink-0"
                onClick={() => status.mutate("reopen")}
              >
                {t("inbox.reopen")}
              </Button>
            ) : (
              <Button
                size="sm"
                variant="secondary"
                className="shrink-0"
                onClick={() => status.mutate("close")}
              >
                {t("inbox.close")}
              </Button>
            )}
          </div>
        </div>
      ) : null}
      {(status.error ?? assign.error) ? (
        <div className="px-5 pt-4">
          <Alert tone="danger">{(status.error ?? assign.error)?.message}</Alert>
        </div>
      ) : null}
      {!th.flagged ? (
        <div className="border-b border-rule px-5 py-3 empty:hidden">
          <AiThreadTools threadId={th.id} />
        </div>
      ) : null}
      <ol className="divide-y divide-rule" aria-label={t("inbox.messages")}>
        {(messages.data ?? []).map((m) => {
          const internal = m.direction === "internal";
          return (
            <li key={m.id} className="px-5 py-3 text-sm">
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{m.author_name}</span> ·{" "}
                <time dateTime={m.created_at}>{formatDateTime(m.created_at, i18n.language)}</time> ·{" "}
                {internal ? (
                  <span className="font-semibold text-foreground">{t("inbox.internalNote")}</span>
                ) : m.channel === "chat" ? (
                  t("inbox.chat")
                ) : (
                  t(`comms.channel.${m.channel}`)
                )}
                {m.delivery_status
                  ? ` · ${t(`designS8.messageStatus.${m.delivery_status}`, { defaultValue: m.delivery_status })}`
                  : ""}
              </p>
              <p
                className={`mt-1 whitespace-pre-wrap ${internal ? "rounded-md border border-border px-3 py-2" : ""}`}
              >
                {m.body}
              </p>
              {m.attachments.length ? (
                <ul className="mt-1.5 space-y-0.5 text-xs">
                  {m.attachments.map((a) => (
                    <li key={a.id} className="flex items-center gap-1.5">
                      <Paperclip
                        aria-hidden="true"
                        strokeWidth={1.75}
                        className="size-3.5 text-muted-foreground"
                      />
                      {a.filename}
                    </li>
                  ))}
                </ul>
              ) : null}
              {m.flags.length ? (
                <p className="mt-1 text-xs font-medium text-danger">
                  {t("inbox.flags", {
                    flags: m.flags.map((f) => t(`inbox.flag.${f}`)).join(", "),
                  })}
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>
      {canReply ? <Composer thread={th} /> : null}
    </section>
  );
}

/** The team inbox (E13-T11): email, text, WhatsApp and portal conversations with
 * assignment, snooze, internal notes, canned replies and a reply-time target. A list and a
 * reading pane: the conversation leads, the list is the narrower column; on phones the list
 * gives way to the conversation once one is chosen. */
export function InboxPage() {
  const { t } = useTranslation();
  const phone = useIsPhone();
  const params = new URLSearchParams(window.location.search);
  const [box, setBox] = useState<Box>("open");
  const [selected, setSelected] = useState<string | null>(params.get("thread"));
  const counts = useQuery({
    queryKey: ["threads", "counts"],
    refetchInterval: POLL_MS,
    queryFn: async () => unwrap(await api.GET("/api/v1/threads/counts")),
  });
  const showList = !phone || !selected;
  const showConversation = !phone || Boolean(selected);
  return (
    <section>
      <PageHeader title={t("inbox.title")} className="mb-4" />
      <nav
        aria-label={t("inbox.boxes")}
        className="relative mb-6 flex gap-1 overflow-x-auto border-b border-border [scrollbar-width:none]"
      >
        {BOXES.map((b) => {
          const count =
            counts.data && b in counts.data ? counts.data[b as keyof typeof counts.data] : null;
          return (
            <button
              key={b}
              type="button"
              aria-pressed={box === b}
              onClick={() => setBox(b)}
              className="-mb-px flex shrink-0 items-center gap-1.5 border-b-2 border-transparent px-3 py-2 text-sm whitespace-nowrap text-muted-foreground hover:text-foreground aria-pressed:border-foreground aria-pressed:font-semibold aria-pressed:text-foreground"
            >
              {t(`inbox.box.${b}`)}
              {count !== null ? (
                <>
                  {count && WAITING.includes(b) ? (
                    <CountPill count={count} />
                  ) : (
                    <span aria-hidden="true" className="font-normal tabular-nums">
                      {count}
                    </span>
                  )}
                  <span className="sr-only"> ({count})</span>
                </>
              ) : null}
            </button>
          );
        })}
      </nav>
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        {showList ? (
          <ThreadList
            box={box}
            selected={selected}
            onSelect={(id) => {
              setSelected(id);
              if (phone) window.scrollTo?.({ top: 0 });
            }}
          />
        ) : null}
        {showConversation ? (
          <div className="min-w-0">
            {phone ? (
              <button
                type="button"
                className="mb-3 flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground hover:underline"
                onClick={() => setSelected(null)}
              >
                <ChevronLeft aria-hidden="true" className="size-4" strokeWidth={1.75} />
                {t("inbox.conversations")}
              </button>
            ) : null}
            {selected ? (
              <Conversation key={selected} id={selected} />
            ) : (
              <p className="rounded-xl border border-border bg-surface px-5 py-10 text-center text-sm text-muted-foreground">
                {t("inbox.pick")}
              </p>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}
