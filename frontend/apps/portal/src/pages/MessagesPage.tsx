import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  cn,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Paperclip } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, uploadFile, usePortalMe } from "../api";
import { FileField, PanelEmpty, PortalHeader, TextAreaField } from "../layout/PortalPage";

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
  const upload = useMutation({
    mutationFn: async (files: FileList) => Promise.all(Array.from(files).map(uploadFile)),
    onSuccess: onChange,
  });
  return (
    <div className="space-y-1">
      <FileField
        label={t("portalMessages.attach")}
        multiple
        onChange={(e) => (e.target.files?.length ? upload.mutate(e.target.files) : undefined)}
      />
      {upload.isPending ? <Spinner label={t("portalMessages.uploading")} /> : null}
      {upload.error ? (
        <p role="alert" className="text-xs text-danger">
          {t("portalMessages.uploadFailed")}
        </p>
      ) : null}
    </div>
  );
}

function threadTitle(row: { subject: string; with_name?: string }, none: string): string {
  return `${row.subject || none}${row.with_name ? ` · ${row.with_name}` : ""}`;
}

/** The reading pane: the conversation's heading, its messages as ruled rows (a caption line of
 * who and when over the text), and the reply form under a register rule. */
function Conversation({ who, id, onBack }: { who: Who; id: string; onBack: () => void }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const messaging = useMessaging(who);
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<string[]>([]);
  const back = useRef<HTMLButtonElement>(null);
  useEffect(() => back.current?.focus(), [id]);
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
  return (
    <div className="space-y-3">
      <button
        ref={back}
        type="button"
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
      >
        <ChevronLeft aria-hidden="true" className="size-4" strokeWidth={1.75} />
        {t("portalMessages.conversations")}
      </button>
      {!thread.data ? (
        <Spinner label={t("grid.loading")} />
      ) : (
        <section
          aria-labelledby="conversation-title"
          className="rounded-xl border border-border bg-surface"
        >
          <h2
            id="conversation-title"
            className="border-b border-border px-5 py-3.5 text-base font-semibold"
          >
            {threadTitle(thread.data, t("portalMessages.noSubject"))}
          </h2>
          <ol className="divide-y divide-rule" aria-label={t("portalMessages.messages")}>
            {thread.data.messages.map((m) => (
              <li key={m.id} className="space-y-1 px-5 py-3 text-sm">
                <p className="text-xs text-muted-foreground tabular-nums">
                  {m.mine ? t("portalMessages.you") : m.author_name} ·{" "}
                  {formatDateTime(m.created_at, i18n.language)}
                </p>
                <p className="whitespace-pre-wrap">{m.body}</p>
                {m.attachments.length ? (
                  <ul className="space-y-0.5 text-xs text-muted-foreground">
                    {m.attachments.map((a) => (
                      <li key={a.id} className="flex items-center gap-1.5">
                        <Paperclip aria-hidden="true" className="size-3.5" strokeWidth={1.75} />
                        {t("portalMessages.attachment", { name: a.filename })}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ol>
          <form
            aria-label={t("portalMessages.reply")}
            className="border-t border-border"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              send.mutate();
            }}
          >
            <div className="space-y-3 px-5 py-4">
              <TextAreaField
                label={t("portalMessages.yourMessage")}
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />
              <Attach onChange={setFiles} />
              {send.error ? <Alert tone="danger">{send.error.message}</Alert> : null}
            </div>
            <PanelFooter>
              <Button type="submit" disabled={!body.trim() || send.isPending}>
                {t("portalMessages.send")}
              </Button>
            </PanelFooter>
          </form>
        </section>
      )}
    </div>
  );
}

function NewConversation({
  who,
  canChoose,
  onStarted,
  onCancel,
}: {
  who: Who;
  canChoose: boolean;
  onStarted: (id: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const messaging = useMessaging(who);
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
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        start.mutate();
      }}
    >
      <RuledPanel title={t("portalMessages.new")} flush>
        <div className="grid gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
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
          <TextAreaField
            className="sm:col-span-2"
            label={t("portalMessages.yourMessage")}
            rows={4}
            required
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="sm:col-span-2">
            <Attach onChange={setFiles} />
          </div>
          {start.error ? (
            <Alert tone="danger" className="sm:col-span-2">
              {start.error.message}
            </Alert>
          ) : null}
        </div>
        <PanelFooter>
          <Button type="submit" disabled={!body.trim() || start.isPending}>
            {t("portalMessages.send")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            className="text-muted-foreground hover:text-foreground"
            onClick={onCancel}
          >
            {t("common.cancel")}
          </Button>
        </PanelFooter>
      </RuledPanel>
    </form>
  );
}

/** Messages with the tutoring company and, when allowed, between families and tutors
 * (E15-T09 / E16 on the E13 inbox). Staff can read every conversation. The portal's column
 * is narrow, so one pane shows at a time: the list, or a conversation with a way back. */
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
    <div className="space-y-6">
      <PortalHeader
        className="mb-0"
        title={t("portalMessages.title")}
        actions={
          selected ? null : (
            <Button size="sm" onClick={() => setComposing((v) => !v)} aria-expanded={composing}>
              {t("portalMessages.new")}
            </Button>
          )
        }
      />
      {selected ? (
        <Conversation who={who} id={selected} onBack={() => setSelected(null)} />
      ) : (
        <>
          {composing ? (
            <NewConversation
              who={who}
              canChoose={canChoose}
              onCancel={() => setComposing(false)}
              onStarted={(id) => {
                setComposing(false);
                setSelected(id);
              }}
            />
          ) : null}
          {threads.isPending ? (
            <Spinner label={t("grid.loading")} />
          ) : !threads.data?.length ? (
            <div className="rounded-xl border border-border bg-surface">
              <PanelEmpty>{t("portalMessages.none")}</PanelEmpty>
            </div>
          ) : (
            <ul
              className="divide-y divide-rule overflow-hidden rounded-xl border border-border bg-surface"
              aria-label={t("portalMessages.conversations")}
            >
              {threads.data.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className="block w-full px-4 py-2.5 text-left text-sm hover:bg-muted/60"
                    onClick={() => setSelected(row.id)}
                  >
                    <span className="flex items-baseline justify-between gap-3">
                      <span
                        className={cn(
                          "flex min-w-0 items-center gap-2",
                          row.unread ? "font-semibold" : "font-medium",
                        )}
                      >
                        {row.unread ? (
                          <span
                            aria-hidden="true"
                            className="size-1.5 shrink-0 rounded-full bg-margin"
                          />
                        ) : null}
                        <span className="truncate">
                          {threadTitle(row, t("portalMessages.noSubject"))}
                        </span>
                        {row.unread ? (
                          <span className="sr-only">
                            {t("portalMessages.unread", { count: row.unread })}
                          </span>
                        ) : null}
                      </span>
                      {row.last_message_at ? (
                        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                          {formatDateTime(row.last_message_at, i18n.language, undefined, {
                            day: "numeric",
                            month: "short",
                          })}
                        </span>
                      ) : null}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {row.last_message_preview}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

export function MessagesPage() {
  const me = usePortalMe();
  const { t } = useTranslation();
  if (!me.data) return <Spinner label={t("grid.loading")} />;
  if (!me.data.features.messages) return <Alert tone="info">{t("portalMessages.off")}</Alert>;
  return <MessagesView who="family" canChoose={me.data.features.message_tutors} />;
}

export function TutorMessagesPage() {
  return <MessagesView who="tutor" canChoose />;
}
