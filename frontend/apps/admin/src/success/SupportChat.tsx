import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";
import { routePattern, track } from "./analytics";
import { GUIDANCE_KEY } from "./guidance";

function MessageBox({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        maxLength={5000}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
      />
    </div>
  );
}

function Csat({ conversationId }: { conversationId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const rate = useMutation({
    mutationFn: async (score: number) =>
      unwrap(
        await api.POST("/api/v1/surveys/responses", {
          body: { kind: "csat", score, topic: `support:${conversationId}` },
        }),
      ),
    onSuccess: () => {
      track("support.rated");
      void queryClient.invalidateQueries({ queryKey: ["support-conversations"] });
    },
  });
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{t("supportChat.csatQuestion")}</legend>
      <div className="flex flex-wrap gap-1">
        {[1, 2, 3, 4, 5].map((score) => (
          <Button
            key={score}
            size="sm"
            variant="secondary"
            disabled={rate.isPending}
            aria-label={t("supportChat.csatScore", { score })}
            onClick={() => rate.mutate(score)}
          >
            {score}
          </Button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{t("supportChat.csatScale")}</p>
    </fieldset>
  );
}

function Conversation({ id, onBack }: { id: string; onBack: () => void }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [reply, setReply] = useState("");
  const conversation = useQuery({
    queryKey: ["support-conversations", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/support-conversations/{id}", { params: { path: { id } } })),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["support-conversations"] });
    void queryClient.invalidateQueries({ queryKey: GUIDANCE_KEY });
  };
  const send = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/support-conversations/{id}/messages", {
          params: { path: { id } },
          body: { body: reply },
        }),
      ),
    onSuccess: () => {
      setReply("");
      refresh();
    },
  });
  const close = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/support-conversations/{id}/close", { params: { path: { id } } }),
      ),
    onSuccess: refresh,
  });
  const data = conversation.data;
  if (!data) return <Spinner label={t("grid.loading")} />;
  return (
    <div className="space-y-3">
      <Button size="sm" variant="ghost" onClick={onBack}>
        {t("supportChat.back")}
      </Button>
      <h3 className="font-semibold">{data.subject}</h3>
      <p className="text-xs text-muted-foreground">{t(`supportChat.status.${data.status}`)}</p>
      <ol className="space-y-2" aria-label={t("supportChat.messages")}>
        {data.messages.map((message) => (
          <li
            key={message.id}
            className={
              message.from_support
                ? "rounded-md border border-border bg-muted p-2"
                : "rounded-md border border-border p-2"
            }
          >
            <p className="text-xs text-muted-foreground">
              {message.author_name} ·{" "}
              {formatDateTime(message.created_at, i18n.language, undefined, {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </p>
            <p className="whitespace-pre-wrap text-sm">{message.body}</p>
          </li>
        ))}
      </ol>
      {data.status !== "closed" ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (reply.trim()) send.mutate();
          }}
        >
          <MessageBox label={t("supportChat.reply")} value={reply} onChange={setReply} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" size="sm" loading={send.isPending} disabled={!reply.trim()}>
              {t("supportChat.send")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              loading={close.isPending}
              onClick={() => close.mutate()}
            >
              {t("supportChat.close")}
            </Button>
          </div>
        </form>
      ) : null}
      {data.status !== "open" && data.csat_score === null ? <Csat conversationId={id} /> : null}
      {data.csat_score !== null ? (
        <p className="text-sm">{t("supportChat.rated", { score: data.csat_score })}</p>
      ) : null}
    </div>
  );
}

/** Built-in chat with TutorTrack support (E30 FR-30-5): no third-party widget. */
export function SupportChat() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const list = useQuery({
    queryKey: ["support-conversations"],
    queryFn: async () => unwrap(await api.GET("/api/v1/support-conversations")),
  });
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/support-conversations", {
          body: { subject, body, page: routePattern(window.location.pathname) },
        }),
      ),
    onSuccess: (conversation) => {
      track("support.opened");
      setSubject("");
      setBody("");
      setOpenId(conversation.id);
      void queryClient.invalidateQueries({ queryKey: ["support-conversations"] });
    },
  });
  if (openId) return <Conversation id={openId} onBack={() => setOpenId(null)} />;
  const conversations = list.data?.results ?? [];
  return (
    <div className="space-y-4">
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (body.trim()) start.mutate();
        }}
      >
        <h3 className="font-semibold">{t("supportChat.newTitle")}</h3>
        <p className="text-xs text-muted-foreground">{t("supportChat.privacyHint")}</p>
        <TextField
          label={t("supportChat.subject")}
          value={subject}
          maxLength={200}
          onChange={(e) => setSubject(e.target.value)}
        />
        <MessageBox label={t("supportChat.message")} value={body} onChange={setBody} />
        {start.isError ? <Alert tone="danger">{t("supportChat.failed")}</Alert> : null}
        <Button type="submit" size="sm" loading={start.isPending} disabled={!body.trim()}>
          {t("supportChat.send")}
        </Button>
      </form>
      {conversations.length > 0 ? (
        <section className="space-y-2">
          <h3 className="font-semibold">{t("supportChat.yourChats")}</h3>
          <ul className="space-y-1">
            {conversations.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => setOpenId(c.id)}
                  className="w-full rounded-md border border-border p-2 text-left text-sm hover:bg-muted"
                >
                  <span className="font-medium">{c.subject}</span>
                  {c.customer_unread ? (
                    <span className="ml-2 rounded bg-brand px-1 text-xs text-brand-foreground">
                      {t("supportChat.newReply")}
                    </span>
                  ) : null}
                  <span className="block text-xs text-muted-foreground">
                    {t(`supportChat.status.${c.status}`)} ·{" "}
                    {formatDateTime(c.last_message_at, i18n.language, undefined, {
                      dateStyle: "medium",
                    })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
