import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FormPanel,
  PageHeader,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { OrganisationPicker, type OrganisationChoice } from "./OrganisationPicker";

type Notice = components["schemas"]["CustomerNotice"];

/** G6 (FR-29-9): breach, security, service and legal notices to organisations' owners and
 *  admins, sent through comms and written to each organisation's audit log. */
export function CustomerNoticesPage() {
  const { t, i18n } = useTranslation();
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
  const [organisations, setOrganisations] = useState<OrganisationChoice[]>([]);
  const [draft, setDraft] = useState<Notice | null>(null);
  const chosen = templates.data?.find((row) => row.key === template);

  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/platform/customer-notices", {
          body: {
            template,
            variables,
            organisation_ids: organisations.map((organisation) => organisation.id),
          },
        }),
      ),
    onSuccess: (notice) => setDraft(notice),
  });

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title={t("customerNotices.title")} description={t("customerNotices.intro")} />
      {templates.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {draft ? (
        <NoticePreview
          notice={draft}
          onDone={() => {
            setDraft(null);
            setVariables({});
            setOrganisations([]);
            void queryClient.invalidateQueries({ queryKey: ["platform", "customer-notices"] });
          }}
        />
      ) : templates.data ? (
        <FormPanel
          title={t("designS11.platform.newNotice")}
          submit={t("customerNotices.preview")}
          pending={create.isPending}
          onSubmit={() => create.mutate()}
          columns={1}
          error={create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
        >
          <SelectField
            label={t("customerNotices.template")}
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            options={templates.data.map((row) => ({ value: row.key, label: row.title }))}
          />
          {chosen?.variables.map((name) => (
            <TextField
              key={name}
              label={t(`customerNotices.variables.${name}`)}
              value={variables[name] ?? ""}
              onChange={(e) => setVariables({ ...variables, [name]: e.target.value })}
            />
          ))}
          <div>
            <OrganisationPicker
              label={t("followUps.orgPicker.noticeLabel")}
              hint={t("followUps.orgPicker.noticeHint")}
              showLabel
              multiple
              value={null}
              exclude={organisations.map((organisation) => organisation.id)}
              onChange={(organisation) =>
                organisation && setOrganisations([...organisations, organisation])
              }
            />
            {organisations.length ? (
              <ul
                aria-label={t("followUps.orgPicker.chosen")}
                className="mt-2 divide-y divide-rule rounded-lg border border-border"
              >
                {organisations.map((organisation) => (
                  <li
                    key={organisation.id}
                    className="flex items-center justify-between gap-3 py-1.5 pr-1.5 pl-3"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{organisation.name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {organisation.slug}
                      </span>
                    </span>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="text-muted-foreground"
                      aria-label={t("followUps.orgPicker.remove", { name: organisation.name })}
                      onClick={() =>
                        setOrganisations(organisations.filter((o) => o.id !== organisation.id))
                      }
                    >
                      {t("platform.remove")}
                    </Button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </FormPanel>
      ) : null}
      <RuledPanel title={t("customerNotices.history")} flush>
        {history.data?.length ? (
          <PanelRows>
            {history.data.map((notice) => (
              <PanelRow key={notice.id}>
                <p className="font-medium">{notice.subject}</p>
                <p className="text-xs text-muted-foreground tabular-nums">
                  <span className={notice.status === "sent" ? undefined : "text-foreground"}>
                    {t(`customerNotices.status.${notice.status}`)}
                  </span>
                  {notice.sent_at ? ` · ${formatDateTime(notice.sent_at, i18n.language)}` : ""}
                  {" · "}
                  {t("customerNotices.counts", {
                    organisations: notice.organisations_count,
                    people: notice.recipients_count,
                  })}
                </p>
              </PanelRow>
            ))}
          </PanelRows>
        ) : history.data ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">{t("customerNotices.none")}</p>
        ) : null}
      </RuledPanel>
    </div>
  );
}

/** The notice as it will go out, its reach in a sentence, then the reason and Send. */
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
    <form
      aria-labelledby="notice-preview"
      onSubmit={(e) => {
        e.preventDefault();
        send.mutate();
      }}
    >
      <RuledPanel
        title={t("customerNotices.previewTitle")}
        titleId="notice-preview"
        description={
          preview.data ? t("customerNotices.goesTo", { count: preview.data.organisations }) : null
        }
        flush
      >
        <div className="space-y-4 px-5 py-4">
          {preview.data ? (
            <div className="max-w-2xl space-y-2">
              <p className="font-medium">{preview.data.subject}</p>
              <div className="rounded-md border border-border px-3 py-2 text-sm whitespace-pre-wrap">
                {preview.data.body}
              </div>
            </div>
          ) : (
            <Spinner label={t("grid.loading")} />
          )}
          <div className="max-w-sm">
            <TextField
              label={t("customerNotices.reason")}
              hint={t("customerNotices.reasonHint")}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
            />
          </div>
          {send.error ? <Alert tone="danger">{send.error.message}</Alert> : null}
        </div>
        <PanelFooter>
          <Button type="button" variant="secondary" onClick={onDone}>
            {t("customerNotices.discard")}
          </Button>
          <Button type="submit" loading={send.isPending} disabled={!reason.trim()}>
            {t("customerNotices.send")}
          </Button>
        </PanelFooter>
      </RuledPanel>
    </form>
  );
}
