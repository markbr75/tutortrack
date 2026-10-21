import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Panel, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { Documents } from "./Documents";
import { textToHtml } from "./html";

type NoteVisibility = components["schemas"]["NoteVisibilityEnum"];

export interface TargetRef {
  target_type: string;
  target_id: string;
}

function Notes({ target }: { target: TargetRef }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canCreate = usePermission("crm.note.create");
  const canStaffOnly = usePermission("crm.note.view_staff_only");
  const bodyId = useId();
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<NoteVisibility>(
    canStaffOnly ? "staff_only" : "staff_and_tutors",
  );
  const notes = useQuery({
    queryKey: ["notes", target],
    queryFn: async () => unwrap(await api.GET("/api/v1/notes", { params: { query: target } })),
  });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/notes", {
          body: { ...target, body: textToHtml(body), visibility },
        }),
      ),
    onSuccess: () => {
      setBody("");
      void queryClient.invalidateQueries({ queryKey: ["notes", target] });
      void queryClient.invalidateQueries({ queryKey: ["timeline", target] });
    },
  });
  const errors = fieldErrors(add.error);
  return (
    <div className="space-y-4">
      {canCreate ? (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (body.trim()) add.mutate();
          }}
        >
          <div>
            <label htmlFor={bodyId} className="mb-1 block text-sm font-medium">
              {t("crm.note.add")}
            </label>
            <textarea
              id={bodyId}
              rows={3}
              value={body}
              aria-invalid={errors.body ? true : undefined}
              onChange={(e) => setBody(e.target.value)}
              className="w-full rounded-md border border-field bg-surface px-3 py-2 text-sm"
            />
            {errors.body ? <p className="mt-1 text-xs text-danger">{errors.body}</p> : null}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <SelectField
              label={t("crm.note.visibility")}
              value={visibility}
              onChange={(e) => setVisibility(e.target.value as NoteVisibility)}
              options={(
                [
                  ...(canStaffOnly ? ["staff_only"] : []),
                  "staff_and_tutors",
                  "shared_with_client",
                ] as const
              ).map((v) => ({ value: v, label: t(`crm.note.${v}`) }))}
            />
            <Button type="submit" disabled={add.isPending}>
              {t("crm.note.save")}
            </Button>
          </div>
        </form>
      ) : null}
      {notes.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {notes.data?.results.length ? (
        <ul className="divide-y divide-rule border-t border-rule">
          {notes.data.results.map((note) => (
            <li key={note.id} className="py-2.5 text-sm">
              {/* The server stores sanitised HTML (nh3 allow-list). */}
              <div className="prose prose-sm" dangerouslySetInnerHTML={{ __html: note.body }} />
              <p className="mt-0.5 text-xs text-muted-foreground">
                <time dateTime={note.created_at}>
                  {formatDateTime(note.created_at, i18n.language)}
                </time>{" "}
                · {t(`crm.note.${note.visibility ?? "staff_only"}`)}
                {note.pinned ? ` · ${t("crm.note.pinned")}` : ""}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
      {notes.data && notes.data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("crm.note.none")}</p>
      ) : null}
    </div>
  );
}

function Tasks({ target }: { target: TargetRef }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canCreate = usePermission("crm.task.create");
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const tasks = useQuery({
    queryKey: ["tasks", target],
    queryFn: async () => unwrap(await api.GET("/api/v1/tasks", { params: { query: target } })),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    void queryClient.invalidateQueries({ queryKey: ["timeline", target] });
  };
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tasks", {
          body: { ...target, title, due_at: due ? new Date(due).toISOString() : null },
        }),
      ),
    onSuccess: () => {
      setTitle("");
      setDue("");
      refresh();
    },
  });
  return (
    <div className="space-y-4">
      {canCreate ? (
        <form
          className="grid gap-3 sm:grid-cols-[1fr_14rem_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) add.mutate();
          }}
        >
          <TextField
            label={t("crm.task.title")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            error={fieldErrors(add.error).title}
          />
          <TextField
            label={t("crm.task.due")}
            type="datetime-local"
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
          <Button type="submit" disabled={add.isPending}>
            {t("crm.task.add")}
          </Button>
        </form>
      ) : null}
      <TaskList tasks={tasks.data?.results ?? []} onChanged={refresh} />
      {tasks.data && tasks.data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("crm.task.none")}</p>
      ) : null}
    </div>
  );
}

type Task = components["schemas"]["Task"];

/** Tasks with a "complete" checkbox; overdue ones are flagged in text, not only colour. */
export function TaskList({ tasks, onChanged }: { tasks: Task[]; onChanged: () => void }) {
  const { t, i18n } = useTranslation();
  const canEdit = usePermission("crm.task.edit");
  const complete = useMutation({
    mutationFn: async ({ id, done }: { id: string; done: boolean }) =>
      unwrap(
        await api.PATCH("/api/v1/tasks/{id}", {
          params: { path: { id } },
          body: { status: done ? "done" : "open" },
        }),
      ),
    onSuccess: onChanged,
  });
  return (
    <ul className="divide-y divide-rule">
      {tasks.map((task) => (
        <li key={task.id} className="flex items-start gap-3 py-2.5 text-sm">
          <input
            type="checkbox"
            className="mt-1 size-4"
            aria-label={t("crm.task.complete", { title: task.title })}
            checked={task.status === "done"}
            disabled={!canEdit || complete.isPending}
            onChange={(e) => complete.mutate({ id: task.id, done: e.target.checked })}
          />
          <div className="min-w-0">
            <p
              className={
                task.status === "done" ? "text-muted-foreground line-through" : "font-medium"
              }
            >
              {task.title}
            </p>
            <p className="text-xs text-muted-foreground">
              {task.due_at
                ? t("crm.task.dueOn", { when: formatDateTime(task.due_at, i18n.language) })
                : t("crm.task.noDue")}
              {task.is_overdue ? (
                <>
                  {" · "}
                  <span className="font-semibold text-margin">{t("crm.task.overdue")}</span>
                </>
              ) : null}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

function Timeline({ target }: { target: TargetRef }) {
  const { t, i18n } = useTranslation();
  const timeline = useQuery({
    queryKey: ["timeline", target],
    queryFn: async () => unwrap(await api.GET("/api/v1/timeline", { params: { query: target } })),
  });
  if (timeline.isPending) return <Spinner label={t("grid.loading")} />;
  if (timeline.isError) return <Alert tone="danger">{t("errors.generic")}</Alert>;
  if (timeline.data.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("crm.timeline.none")}</p>;
  }
  return (
    <ol className="divide-y divide-rule">
      {timeline.data.map((item) => (
        <li
          key={`${item.kind}-${item.id}`}
          className="grid gap-x-4 gap-y-0.5 py-2.5 text-sm sm:grid-cols-[9rem_minmax(0,1fr)]"
        >
          <time dateTime={item.at} className="text-xs text-muted-foreground sm:pt-0.5">
            {formatDateTime(item.at, i18n.language)}
          </time>
          <div className="min-w-0">
            <p className="break-words">
              {item.kind === "note" ? stripTags(item.body) : item.title || item.body}
            </p>
            <p className="text-xs text-muted-foreground">
              {t(
                ["lesson", "invoice", "payment"].includes(item.kind)
                  ? `peopleTools.timeline.${item.kind}`
                  : `crm.timeline.${item.kind}`,
              )}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function stripTags(html: string): string {
  return new DOMParser().parseFromString(html, "text/html").body.textContent ?? "";
}

const TABS = ["notes", "tasks", "timeline"] as const;
type Tab = (typeof TABS)[number] | "documents";

/** Notes, tasks and the activity timeline for any record (E05 FR-05-7, 8, 10). */
export function RecordActivity({ target }: { target: TargetRef }) {
  const { t } = useTranslation();
  const canSeeDocuments = usePermission("crm.document.view");
  const [tab, setTab] = useState<Tab>("notes");
  return (
    <Panel
      title={t("crm.activity")}
      flush
      bodyClassName="pb-5 [&_[role=tablist]]:px-5 [&_[role=tablist]]:[mask-image:none] [&_[role=tabpanel]]:px-5"
    >
      <Tabs
        label={t("crm.activity")}
        tabs={[
          ...TABS.map((key): { key: Tab; label: string } => ({ key, label: t(`crm.tabs.${key}`) })),
          ...(canSeeDocuments ? [{ key: "documents" as Tab, label: t("esign.tab") }] : []),
        ]}
        value={tab}
        onChange={setTab}
      >
        {tab === "notes" ? <Notes target={target} /> : null}
        {tab === "tasks" ? <Tasks target={target} /> : null}
        {tab === "timeline" ? <Timeline target={target} /> : null}
        {tab === "documents" ? <Documents target={target} /> : null}
      </Tabs>
    </Panel>
  );
}
