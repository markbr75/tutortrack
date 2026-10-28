import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Panel, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { countOf } from "./common";

type Draft = components["schemas"]["WorkflowPreviewDraftRequest"];
type PreviewStep = components["schemas"]["WorkflowPreviewStep"];

/**
 * Preview for a record (E33 FR-33-3): choose a real family, lesson or enquiry and see the
 * timeline with real dates, which path each split takes and what each step would send.
 * Nothing is sent or changed. With unsaved changes it previews them.
 */
export function PreviewPanel({
  id,
  recordLabel,
  draft,
  blocked,
}: {
  id: string;
  recordLabel: string;
  draft: Draft | null;
  blocked: boolean;
}) {
  const { t, i18n } = useTranslation();
  const [search, setSearch] = useState("");
  const [record, setRecord] = useState("");
  const records = useQuery({
    queryKey: ["workflow-records", id, search],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/workflows/{id}/records", {
          params: { path: { id }, query: search ? { q: search } : {} },
        }),
      ),
  });
  const preview = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/workflows/{id}/preview", {
          params: { path: { id } },
          body: { subject_id: record, ...(draft ? { draft } : {}) },
        }),
      ),
  });
  const when = (iso: string) => formatDateTime(iso, i18n.language);
  const result = preview.data;
  const options = records.data ?? [];
  return (
    <Panel title={t("workflows.preview.title")} bodyClassName="space-y-4">
      <p className="text-sm text-muted-foreground">{t("workflows.preview.help")}</p>
      <form
        className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          preview.mutate();
        }}
      >
        <TextField
          label={t("workflows.preview.find", { record: recordLabel })}
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <SelectField
          label={t("workflows.preview.record", { record: recordLabel })}
          value={record}
          onChange={(e) => setRecord(e.target.value)}
          options={[
            {
              value: "",
              label: options.length ? t("workflows.preview.choose") : t("workflows.preview.none"),
            },
            ...options.map((r) => ({ value: r.id, label: r.label })),
          ]}
        />
        <Button
          type="submit"
          variant="secondary"
          disabled={!record || blocked}
          loading={preview.isPending}
        >
          {t("workflows.preview.show")}
        </Button>
      </form>
      {blocked ? <p className="text-sm text-danger">{t("workflows.preview.fixFirst")}</p> : null}
      {draft && !blocked ? (
        <p className="text-sm text-muted-foreground">{t("workflows.preview.unsaved")}</p>
      ) : null}
      {preview.error ? <Alert tone="danger">{preview.error.message}</Alert> : null}
      {result ? (
        <section
          aria-live="polite"
          aria-label={t("workflows.preview.for", { record: result.record.label })}
        >
          <h3 className="text-sm font-semibold">
            {t("workflows.preview.for", { record: result.record.label })}
          </h3>
          {!result.matched ? (
            <p className="mt-2 text-sm">
              {result.failed_checks.length
                ? t("workflows.preview.wouldNotStart", { checks: result.failed_checks.join(", ") })
                : t("workflows.preview.wouldNotStartChecks")}
            </p>
          ) : !result.start ? (
            <p className="mt-2 text-sm">{t("workflows.preview.noDate")}</p>
          ) : (
            <>
              <p className="mt-2 text-sm">
                {t(
                  result.start_passed
                    ? "workflows.preview.startedAt"
                    : "workflows.preview.startsAt",
                  {
                    when: when(result.start),
                  },
                )}
                {result.starts.length > 1
                  ? ` ${t("workflows.preview.alsoAt", {
                      when: result.starts
                        .filter((s) => s !== result.start)
                        .map(when)
                        .join(", "),
                    })}`
                  : null}
              </p>
              {result.stop_when.length ? (
                <p className="text-sm text-muted-foreground">
                  {t("workflows.preview.stopsIf", { events: result.stop_when.join(", ") })}
                </p>
              ) : null}
              <ol className="mt-3 space-y-2 border-l-2 border-rule pl-4">
                {result.steps.map((step) => (
                  <PreviewRow key={step.key} step={step} when={when} />
                ))}
              </ol>
              <p className="mt-3 text-xs text-muted-foreground">{t("workflows.preview.asNow")}</p>
            </>
          )}
        </section>
      ) : null}
    </Panel>
  );
}

function PreviewRow({ step, when }: { step: PreviewStep; when: (iso: string) => string }) {
  const { t } = useTranslation();
  const path =
    step.path === "yes" ? t("workflows.yes") : step.path === "no" ? t("workflows.no") : "";
  const text =
    step.type === "branch"
      ? t("workflows.preview.answer", {
          question: step.questions.join(t("workflows.and")),
          answer: step.answer === "yes" ? t("workflows.yes") : t("workflows.no"),
        })
      : step.description;
  return (
    <li className={step.path ? "ml-4 text-sm" : "text-sm"}>
      <span className="block text-xs text-muted-foreground tabular-nums">
        {[path ? t("workflows.preview.onPath", { path }) : "", when(step.at)]
          .filter(Boolean)
          .join(" · ")}
      </span>
      <span
        className={
          !step.ok
            ? "font-medium text-danger"
            : step.skipped
              ? "text-muted-foreground line-through"
              : ""
        }
      >
        {text}
      </span>
      {step.skipped ? (
        <span className="block text-xs text-muted-foreground">
          {t("workflows.preview.skipped", { question: step.questions.join(t("workflows.and")) })}
        </span>
      ) : step.note ? (
        <span className="block text-xs text-muted-foreground">{step.note}</span>
      ) : null}
      {step.message && !step.skipped ? (
        <span className="block text-xs">
          {t("workflows.preview.sends", { message: step.message.label })}{" "}
          <Link
            to="/settings/notifications"
            search={{ edit: step.message.type }}
            className="font-medium underline underline-offset-2"
          >
            {t("workflows.editWording")}
          </Link>
        </span>
      ) : null}
    </li>
  );
}

/** Coming up (E33 FR-33-3): a scheduled or date start's next 5 dates and how many records
 * each would pick ("1 Dec, 06:00: 38 families"). */
export function ComingUp({
  id,
  version,
  recordType,
  changed,
}: {
  id: string;
  version: number;
  recordType: string;
  changed: boolean;
}) {
  const { t, i18n } = useTranslation();
  const upcoming = useQuery({
    queryKey: ["workflow-upcoming", id, version],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/workflows/{id}/upcoming", { params: { path: { id } } })),
  });
  const data = upcoming.data;
  return (
    <Panel title={t("workflows.comingUp.title")} bodyClassName="space-y-3">
      {!data ? (
        <Spinner label={t("grid.loading")} />
      ) : data.dates.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {data.looked_ahead_days
            ? t("workflows.comingUp.noneFor", { count: data.looked_ahead_days })
            : t("workflows.comingUp.none")}
        </p>
      ) : (
        <ul className="space-y-1 text-sm tabular-nums">
          {data.dates.map((d) => (
            <li key={d.at}>
              {t("workflows.comingUp.row", {
                when: formatDateTime(d.at, i18n.language),
                count: countOf(t, recordType, d.count),
              })}
            </li>
          ))}
        </ul>
      )}
      {data?.before_checks ? (
        <p className="text-xs text-muted-foreground">{t("workflows.comingUp.beforeChecks")}</p>
      ) : null}
      {changed ? (
        <p className="text-xs text-muted-foreground">{t("workflows.comingUp.saveToSee")}</p>
      ) : null}
    </Panel>
  );
}
