import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState, type FormEvent } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { actionLink, type BulkEntity, type useSelection } from "./listHelpers";

/** Gap batch G1 (FR-05-11/12): bulk actions and exports shared by the people list grids. */

type BulkJob = components["schemas"]["BulkJob"];

/** Export links for the current filters (CSV and Excel), FR-05-11. */
export function ExportLinks({ path, params }: { path: string; params: Record<string, string> }) {
  const { t } = useTranslation();
  const query = (format: string) =>
    new URLSearchParams({ ...params, file_format: format }).toString();
  return (
    <>
      <a className={actionLink} href={`${path}?${query("csv")}`}>
        {t("peopleTools.export.csv")}
      </a>
      <a className={actionLink} href={`${path}?${query("xlsx")}`}>
        {t("peopleTools.export.xlsx")}
      </a>
    </>
  );
}

const ENTITY_PATH: Record<BulkEntity, string> = {
  client: "clients",
  contact: "contacts",
  student: "students",
  tutor: "tutors",
};

function SendMessageForm({
  count,
  onSend,
  onCancel,
  pending,
  error,
}: {
  count: number;
  onSend: (params: Record<string, string>) => void;
  onCancel: () => void;
  pending: boolean;
  error: unknown;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const [draft, setDraft] = useState({
    channel: "email",
    purpose: "service",
    subject: "",
    body: "",
  });
  const errors = fieldErrors(error);
  const bodyId = useId();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSend(draft);
  };
  return (
    <form
      aria-labelledby={titleId}
      onSubmit={submit}
      className="mt-3 grid gap-3 rounded-md border border-border p-4"
    >
      <h2 id={titleId} className="font-semibold">
        {t("peopleTools.message.title")}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t("peopleTools.message.recipients", { count })}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField
          label={t("peopleTools.message.channel")}
          value={draft.channel}
          onChange={(e) => setDraft((d) => ({ ...d, channel: e.target.value }))}
          options={[
            { value: "email", label: t("peopleTools.message.email") },
            { value: "sms", label: t("peopleTools.message.sms") },
          ]}
        />
        <SelectField
          label={t("peopleTools.message.purpose")}
          value={draft.purpose}
          hint={draft.purpose === "marketing" ? t("peopleTools.message.marketingHint") : undefined}
          onChange={(e) => setDraft((d) => ({ ...d, purpose: e.target.value }))}
          options={[
            { value: "service", label: t("peopleTools.message.service") },
            { value: "marketing", label: t("peopleTools.message.marketing") },
          ]}
        />
      </div>
      {draft.channel === "email" ? (
        <TextField
          label={t("peopleTools.message.subject")}
          value={draft.subject}
          error={errors.subject}
          onChange={(e) => setDraft((d) => ({ ...d, subject: e.target.value }))}
        />
      ) : null}
      <div className="grid gap-1.5">
        <label htmlFor={bodyId} className="text-sm font-medium">
          {t("peopleTools.message.body")}
        </label>
        <p id={`${bodyId}-hint`} className="text-xs text-muted-foreground">
          {t("peopleTools.message.bodyHint", { token: "{{ recipient.first_name }}" })}
        </p>
        <textarea
          id={bodyId}
          rows={5}
          className="rounded-md border border-border bg-background p-2 text-sm"
          value={draft.body}
          aria-describedby={errors.body ? `${bodyId}-error` : `${bodyId}-hint`}
          aria-invalid={errors.body ? true : undefined}
          onChange={(e) => setDraft((d) => ({ ...d, body: e.target.value }))}
        />
        {errors.body ? (
          <p id={`${bodyId}-error`} role="alert" className="text-xs text-danger">
            {errors.body}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={pending}>
          {t("peopleTools.message.send")}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          {t("peopleTools.message.cancel")}
        </Button>
      </div>
    </form>
  );
}

function JobProgress({ jobId }: { jobId: string }) {
  const { t } = useTranslation();
  const job = useQuery({
    queryKey: ["bulk-jobs", jobId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/bulk-jobs/{id}", { params: { path: { id: jobId } } })),
    refetchInterval: (query) => {
      const status = (query.state.data as BulkJob | undefined)?.status;
      return status === "completed" || status === "failed" ? false : 1500;
    },
  });
  const data = job.data;
  if (!data) return null;
  const errors = Object.entries((data.errors ?? {}) as Record<string, string>);
  const finished = data.status === "completed" || data.status === "failed";
  return (
    <div role="status" aria-live="polite" className="mt-3">
      <p className="text-sm">
        {finished
          ? t("peopleTools.bulk.done", { succeeded: data.succeeded, total: data.total })
          : t("peopleTools.bulk.running", { processed: data.processed, total: data.total })}
      </p>
      {finished && errors.length ? (
        <div className="mt-1 text-sm">
          <p>{t("peopleTools.bulk.failures", { count: errors.length })}</p>
          <ul className="list-disc pl-5">
            {errors.map(([id, reason]) => (
              <li key={id}>
                {reason
                  .split(", ")
                  .map((r) => t(`peopleTools.bulk.reason.${r}`, { defaultValue: r }))
                  .join(", ")}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** The bulk action bar (FR-05-12): send a message, invite to the portal, export the
 * selected rows, or merge two of them. Actions run as background jobs with progress. */
export function BulkBar({
  entity,
  selection,
  mergeEntity,
}: {
  entity: BulkEntity;
  selection: ReturnType<typeof useSelection>;
  mergeEntity?: "clients" | "contacts" | "students";
}) {
  const { t } = useTranslation();
  const canRun = usePermission("crm.bulk.run");
  const canMessage = usePermission("comms.broadcast.send");
  const canInvite = usePermission(`people.${entity}.edit`);
  const canExport = usePermission(`people.${entity}.export`);
  const canMerge = usePermission("people.merge");
  const [writing, setWriting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: async ({ action, params }: { action: string; params: Record<string, string> }) =>
      unwrap(
        await api.POST("/api/v1/bulk/{entity}/{bulk_action}", {
          params: { path: { entity, bulk_action: action } },
          body: { target_ids: selection.selected, params },
        }),
      ),
    onSuccess: (job) => {
      setWriting(false);
      setJobId(job.id);
    },
  });
  const count = selection.selected.length;
  if (count === 0) return jobId ? <JobProgress jobId={jobId} /> : null;
  const ids = selection.selected.join(",");
  const exportHref = (format: string) =>
    `/api/v1/${ENTITY_PATH[entity]}/export?${new URLSearchParams({ ids, file_format: format }).toString()}`;
  const [first, second] = selection.selected;
  return (
    <section aria-label={t("peopleTools.bulk.label")} className="mb-4 rounded-md bg-muted p-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-2 text-sm font-medium">{t("peopleTools.bulk.selected", { count })}</p>
        {canRun && canMessage ? (
          <Button size="sm" variant="secondary" onClick={() => setWriting(true)}>
            {t("peopleTools.bulk.sendMessage")}
          </Button>
        ) : null}
        {canRun && canInvite && (entity === "client" || entity === "contact") ? (
          <Button
            size="sm"
            variant="secondary"
            loading={run.isPending && !writing}
            onClick={() => run.mutate({ action: "invite_portal", params: {} })}
          >
            {t("peopleTools.bulk.invite")}
          </Button>
        ) : null}
        {canExport ? (
          <>
            <a className={actionLink} href={exportHref("csv")}>
              {t("peopleTools.bulk.exportCsv")}
            </a>
            <a className={actionLink} href={exportHref("xlsx")}>
              {t("peopleTools.bulk.exportXlsx")}
            </a>
          </>
        ) : null}
        {canMerge && mergeEntity && count === 2 && first && second ? (
          <Link
            className={actionLink}
            to="/people/merge/$entity/$sourceId/$targetId"
            params={{ entity: mergeEntity, sourceId: second, targetId: first }}
          >
            {t("peopleTools.bulk.merge")}
          </Link>
        ) : null}
        <Button size="sm" variant="ghost" onClick={selection.clear}>
          {t("peopleTools.bulk.clear")}
        </Button>
      </div>
      {writing ? (
        <SendMessageForm
          count={count}
          pending={run.isPending}
          error={run.error}
          onCancel={() => setWriting(false)}
          onSend={(params) => run.mutate({ action: "send_message", params })}
        />
      ) : null}
      {run.error && !writing ? <Alert tone="danger">{t("errors.generic")}</Alert> : null}
      {jobId ? <JobProgress jobId={jobId} /> : null}
    </section>
  );
}
