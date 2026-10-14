import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { api, uploadFile, usePortalMe } from "../api";

type ThreadRow = components["schemas"]["PortalThread"];
type ThreadDetail = components["schemas"]["PortalThreadDetail"];
type Option = { id: string; name: string };
type Who = "family" | "tutor";

const POLL_MS = 30_000;

/** The calls differ by who is signed in (family or tutor portal); the screens don't. */
function useMessaging(who: Who) {
  const listKey = ["portal", "threads", who];
  const list = async (): Promise<ThreadRow[]> =>
    who === "family"
      ? unwrap(await api.GET("/api/v1/portal/threads"))
      : unwrap(await api.GET("/api/v1/tutor/threads"));
  const detail = async (id: string): Promise<ThreadDetail> => {
    const path = { params: { path: { thread_id: id } } };
    return who === "family"
      ? unwrap(await api.GET("/api/v1/portal/threads/{thread_id}", path))
      : unwrap(await api.GET("/api/v1/tutor/threads/{thread_id}", path));
  };
  const post = async (id: string, body: string, attachments: string[]) => {
    const args = { params: { path: { thread_id: id } }, body: { body, attachments } };
    return who === "family"
      ? unwrap(await api.POST("/api/v1/portal/threads/{thread_id}/messages", args))
      : unwrap(await api.POST("/api/v1/tutor/threads/{thread_id}/messages", args));
  };
  const start = async (values: {
    subject: string;
    body: string;
    to: string;
    attachments: string[];
  }): Promise<ThreadDetail> => {
    const base = { subject: values.subject, body: values.body, attachments: values.attachments };
    return who === "family"
      ? unwrap(
          await api.POST("/api/v1/portal/threads", {
            body: { ...base, tutor: values.to || null },
          }),
        )
      : unwrap(
          await api.POST("/api/v1/tutor/threads", { body: { ...base, client: values.to || null } }),
        );
  };
  const people = async (): Promise<Option[]> =>
    who === "family"
      ? unwrap(await api.GET("/api/v1/portal/messaging/tutors"))
      : unwrap(await api.GET("/api/v1/tutor/messaging/families"));
  return { listKey, list, detail, post, start, people };
}

function Attach({ onChange }: { onChange: (ids: string[]) => void }) {
  const { t } = useTranslation();
  const id = useId();
  const upload = useMutation({
    mutationFn: async (files: FileList) => Promise.all(Array.from(files).map(uploadFile)),
    onSuccess: onChange,
  });
  return (
    <div className="flex flex-col gap-1 text-sm">
      <label htmlFor={id}>{t("portalMessages.attach")}</label>
      <input
        id={id}
        type="file"
        multiple
        onChange={(e) => (e.target.files?.length ? upload.mutate(e.target.files) : undefined)}
      />
      {upload.isPending ? (
        <Spinner className="size-4" label={t("portalMessages.uploading")} />
      ) : null}
      {upload.error ? <p role="alert">{t("portalMessages.uploadFailed")}</p> : null}
    </div>
  );
}

function Conversation({ who, id }: { who: Who; id: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const messaging = useMessaging(who);
  const bodyId = useId();
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<string[]>([]);
  const thread = useQuery({
    queryKey: ["portal", "thread", who, id],
    refetchInterval: POLL_MS,
    queryFn: () => messaging.detail(id),
  });
  const send = useMutation({
    mutationFn: () => messaging.post(id, body, files),
    onSuccess: () => {
      setBody("");
      setFiles([]);
      void queryClient.invalidateQueries({ queryKey: ["portal", "thread", who, id] });
      void queryClient.invalidateQueries({ queryKey: messaging.listKey });
    },
  });
  if (!thread.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  return (
    <section aria-labelledby="conversation-title" className="space-y-3">
      <h2 id="conversation-title" className="font-semibold">
        {thread.data.subject || t("portalMessages.noSubject")}
        {thread.data.with_name ? ` · ${thread.data.with_name}` : ""}
      </h2>
      <ol className="space-y-2" aria-label={t("portalMessages.messages")}>
        {thread.data.messages.map((m) => (
          <li
            key={m.id}
            className={
              m.mine
                ? "ml-8 rounded-md bg-primary/10 p-2 text-sm"
                : "mr-8 rounded-md border border-border p-2 text-sm"
            }
          >
            <p className="text-xs text-muted-foreground">
              {m.mine ? t("portalMessages.you") : m.author_name} ·{" "}
              {formatDateTime(m.created_at, i18n.language)}
            </p>
            <p className="whitespace-pre-wrap">{m.body}</p>
            {m.attachments.length ? (
              <ul className="text-xs">
                {m.attachments.map((a) => (
                  <li key={a.id}>{t("portalMessages.attachment", { name: a.filename })}</li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ol>
      <form
        aria-label={t("portalMessages.reply")}
        className="space-y-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          send.mutate();
        }}
      >
        <label htmlFor={bodyId} className="text-sm font-medium">
          {t("portalMessages.yourMessage")}
        </label>
        <textarea
          id={bodyId}
          rows={3}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          className="w-full rounded-md border border-border bg-background p-2 text-sm"
        />
        <Attach onChange={setFiles} />
        {send.error ? <Alert tone="danger">{send.error.message}</Alert> : null}
        <Button type="submit" disabled={!body.trim() || send.isPending}>
          {t("portalMessages.send")}
        </Button>
      </form>
    </section>
  );
}

function NewConversation({
  who,
  canChoose,
  onStarted,
}: {
  who: Who;
  canChoose: boolean;
  onStarted: (id: string) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const messaging = useMessaging(who);
  const bodyId = useId();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [to, setTo] = useState("");
  const [files, setFiles] = useState<string[]>([]);
  const people = useQuery({
    queryKey: ["portal", "messaging", who, "people"],
    enabled: canChoose,
    queryFn: messaging.people,
  });
  const start = useMutation({
    mutationFn: () => messaging.start({ subject, body, to, attachments: files }),
    onSuccess: (thread) => {
      void queryClient.invalidateQueries({ queryKey: messaging.listKey });
      onStarted(thread.id);
    },
  });
  return (
    <form
      aria-label={t("portalMessages.new")}
      className="space-y-3 rounded-md border border-border p-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        start.mutate();
      }}
    >
      <h2 className="font-semibold">{t("portalMessages.new")}</h2>
      {canChoose && people.data?.length ? (
        <SelectField
          label={t("portalMessages.to")}
          value={to}
          onChange={(e) => setTo(e.target.value)}
          options={[
            { value: "", label: t("portalMessages.toOffice") },
            ...people.data.map((p) => ({ value: p.id, label: p.name })),
          ]}
        />
      ) : null}
      <TextField
        label={t("portalMessages.subject")}
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
      />
      <div className="flex flex-col gap-1">
        <label htmlFor={bodyId} className="text-sm font-medium">
          {t("portalMessages.yourMessage")}
        </label>
        <textarea
          id={bodyId}
          rows={4}
          required
          value={body}
          onChange={(e) => setBody(e.target.value)}
          className="w-full rounded-md border border-border bg-background p-2 text-sm"
        />
      </div>
      <Attach onChange={setFiles} />
      {start.error ? <Alert tone="danger">{start.error.message}</Alert> : null}
      <Button type="submit" disabled={!body.trim() || start.isPending}>
        {t("portalMessages.send")}
      </Button>
    </form>
  );
}

/** Messages with the tutoring company and, when allowed, between families and tutors
 * (E15-T09 / E16 on the E13 inbox). Staff can read every conversation. */
export function MessagesView({ who, canChoose }: { who: Who; canChoose: boolean }) {
  const { t, i18n } = useTranslation();
  const messaging = useMessaging(who);
  const initial = new URLSearchParams(window.location.search).get("thread");
  const [selected, setSelected] = useState<string | null>(initial);
  const [composing, setComposing] = useState(false);
  const threads = useQuery({
    queryKey: messaging.listKey,
    refetchInterval: POLL_MS,
    queryFn: messaging.list,
  });
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t("portalMessages.title")}</h1>
        <Button size="sm" onClick={() => setComposing((v) => !v)} aria-expanded={composing}>
          {t("portalMessages.new")}
        </Button>
      </div>
      {composing ? (
        <NewConversation
          who={who}
          canChoose={canChoose}
          onStarted={(id) => {
            setComposing(false);
            setSelected(id);
          }}
        />
      ) : null}
      {threads.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : !threads.data?.length ? (
        <p className="text-sm text-muted-foreground">{t("portalMessages.none")}</p>
      ) : (
        <ul
          className="divide-y divide-border rounded-md border border-border"
          aria-label={t("portalMessages.conversations")}
        >
          {threads.data.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                className="w-full p-2 text-left text-sm hover:bg-muted aria-[current=true]:bg-muted"
                aria-current={selected === row.id ? "true" : undefined}
                onClick={() => setSelected(row.id)}
              >
                <span className="font-medium">
                  {row.subject || t("portalMessages.noSubject")}
                  {row.with_name ? ` · ${row.with_name}` : ""}
                </span>
                {row.unread ? (
                  <span className="ml-2 rounded bg-primary px-1 text-xs text-primary-foreground">
                    {t("portalMessages.unread", { count: row.unread })}
                  </span>
                ) : null}
                <span className="block truncate text-muted-foreground">
                  {row.last_message_preview}
                  {row.last_message_at
                    ? ` · ${formatDateTime(row.last_message_at, i18n.language)}`
                    : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {selected ? <Conversation who={who} id={selected} /> : null}
    </div>
  );
}

export function MessagesPage() {
  const me = usePortalMe();
  const { t } = useTranslation();
  if (!me.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (!me.data.features.messages) return <Alert tone="info">{t("portalMessages.off")}</Alert>;
  return <MessagesView who="family" canChoose={me.data.features.message_tutors} />;
}

export function TutorMessagesPage() {
  return <MessagesView who="tutor" canChoose />;
}
