import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

type Notice = components["schemas"]["CustomerNotice"];

/** G6 (FR-29-9): breach, security, service and legal notices to organisations' owners and
 *  admins, sent through comms and written to each organisation's audit log. */
export function CustomerNoticesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const templates = useQuery({
    queryKey: ["platform", "notice-templates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/customer-notices/templates")),
  });
  const history = useQuery({
    queryKey: ["platform", "customer-notices"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/customer-notices")),
  });
  const [template, setTemplate] = useState("breach");
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [orgIds, setOrgIds] = useState("");
  const [draft, setDraft] = useState<Notice | null>(null);
  const chosen = templates.data?.find((row) => row.key === template);

  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/platform/customer-notices", {
          body: {
            template,
            variables,
            organisation_ids: orgIds
              .split(/[\s,]+/)
              .map((id) => id.trim())
              .filter(Boolean),
          },
        }),
      ),
    onSuccess: (notice) => setDraft(notice),
  });

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">{t("customerNotices.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("customerNotices.intro")}</p>
      {templates.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      {draft ? (
        <NoticePreview
          notice={draft}
          onDone={() => {
            setDraft(null);
            setVariables({});
            void queryClient.invalidateQueries({ queryKey: ["platform", "customer-notices"] });
          }}
        />
      ) : (
        <form
          className="space-y-3 rounded-lg border border-border p-4"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <SelectField
            label={t("customerNotices.template")}
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            options={(templates.data ?? []).map((row) => ({ value: row.key, label: row.title }))}
          />
          {chosen?.variables.map((name) => (
            <TextField
              key={name}
              label={t(`customerNotices.variables.${name}`)}
              value={variables[name] ?? ""}
              onChange={(e) => setVariables({ ...variables, [name]: e.target.value })}
            />
          ))}
          <TextField
            label={t("customerNotices.organisations")}
            hint={t("customerNotices.organisationsHint")}
            value={orgIds}
            onChange={(e) => setOrgIds(e.target.value)}
          />
          {create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
          <Button type="submit" loading={create.isPending}>
            {t("customerNotices.preview")}
          </Button>
        </form>
      )}
      <section aria-labelledby="notice-history">
        <h2 id="notice-history" className="text-lg font-semibold">
          {t("customerNotices.history")}
        </h2>
        {history.data?.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("customerNotices.none")}</p>
        ) : null}
        <ul className="divide-y divide-border">
          {history.data?.map((notice) => (
            <li key={notice.id} className="py-2 text-sm">
              <p className="font-medium">{notice.subject}</p>
              <p className="text-muted-foreground">
                {t(`customerNotices.status.${notice.status}`)}
                {notice.sent_at ? ` · ${formatDateTime(notice.sent_at)}` : ""}
                {" · "}
                {t("customerNotices.counts", {
                  organisations: notice.organisations_count,
                  people: notice.recipients_count,
                })}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function NoticePreview({ notice, onDone }: { notice: Notice; onDone: () => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const preview = useQuery({
    queryKey: ["platform", "customer-notice-preview", notice.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/platform/customer-notices/{id}/preview", {
          params: { path: { id: notice.id } },
        }),
      ),
  });
  const send = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/platform/customer-notices/{id}/send", {
          params: { path: { id: notice.id } },
          body: { reason },
        }),
      ),
    onSuccess: onDone,
  });
  return (
    <section aria-labelledby="notice-preview" className="space-y-3 rounded-lg border p-4">
      <h2 id="notice-preview" className="text-lg font-semibold">
        {t("customerNotices.previewTitle")}
      </h2>
      {preview.data ? (
        <>
          <p className="text-sm">
            {t("customerNotices.goesTo", { count: preview.data.organisations })}
          </p>
          <p className="font-medium">{preview.data.subject}</p>
          <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">
            {preview.data.body}
          </pre>
        </>
      ) : (
        <Spinner className="size-5" label={t("grid.loading")} />
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send.mutate();
        }}
      >
        <TextField
          label={t("customerNotices.reason")}
          hint={t("customerNotices.reasonHint")}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          required
        />
        <Button type="submit" loading={send.isPending} disabled={!reason.trim()}>
          {t("customerNotices.send")}
        </Button>
        <Button type="button" variant="secondary" onClick={onDone}>
          {t("customerNotices.discard")}
        </Button>
      </form>
      {send.error ? <Alert tone="danger">{send.error.message}</Alert> : null}
    </section>
  );
}
