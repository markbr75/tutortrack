import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
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
              className="w-full rounded-md border border-border bg-background p-2 text-sm"
            />
            {errors.body ? <p className="mt-1 text-sm text-danger">{errors.body}</p> : null}
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
      <ul className="space-y-3">
        {(notes.data?.results ?? []).map((note) => (
          <li key={note.id} className="rounded-md border border-border p-3">
            <p className="mb-1 text-xs text-muted-foreground">
              {formatDateTime(note.created_at, i18n.language)} ·{" "}
              {t(`crm.note.${note.visibility ?? "staff_only"}`)}
              {note.pinned ? ` · ${t("crm.note.pinned")}` : ""}
            </p>
            {/* The server stores sanitised HTML (nh3 allow-list). */}
            <div className="prose prose-sm" dangerouslySetInnerHTML={{ __html: note.body }} />
          </li>
        ))}
      </ul>
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
    <ul className="divide-y divide-border">
      {tasks.map((task) => (
        <li key={task.id} className="flex items-start gap-3 py-2">
          <input
            type="checkbox"
            className="mt-1 size-4"
            aria-label={t("crm.task.complete", { title: task.title })}
            checked={task.status === "done"}
            disabled={!canEdit || complete.isPending}
            onChange={(e) => complete.mutate({ id: task.id, done: e.target.checked })}
          />
          <div>
            <p className={task.status === "done" ? "line-through" : undefined}>{task.title}</p>
            <p className="text-xs text-muted-foreground">
              {task.due_at
                ? t("crm.task.dueOn", { when: formatDateTime(task.due_at, i18n.language) })
                : t("crm.task.noDue")}
              {task.is_overdue ? (
                <span className="ml-2 font-medium text-danger">{t("crm.task.overdue")}</span>
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
    <ol className="space-y-3 border-l border-border pl-4">
      {timeline.data.map((item) => (
        <li key={`${item.kind}-${item.id}`}>
          <p className="text-xs text-muted-foreground">
            {formatDateTime(item.at, i18n.language)} · {t(`crm.timeline.${item.kind}`)}
          </p>
          <p className="text-sm">
            {item.kind === "note" ? stripTags(item.body) : item.title || item.body}
          </p>
        </li>
      ))}
    </ol>
  );
}

function stripTags(html: string): string {
  return new DOMParser().parseFromString(html, "text/html").body.textContent ?? "";
}

const TABS = ["notes", "tasks", "timeline"] as const;
type Tab = (typeof TABS)[number];

/** Notes, tasks and the activity timeline for any record (E05 FR-05-7, 8, 10). */
export function RecordActivity({ target }: { target: TargetRef }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("notes");
  return (
    <section aria-label={t("crm.activity")} className="mt-8">
      <Tabs
        label={t("crm.activity")}
        tabs={TABS.map((key) => ({ key, label: t(`crm.tabs.${key}`) }))}
        value={tab}
        onChange={setTab}
      >
        {tab === "notes" ? <Notes target={target} /> : null}
        {tab === "tasks" ? <Tasks target={target} /> : null}
        {tab === "timeline" ? <Timeline target={target} /> : null}
      </Tabs>
    </section>
  );
}
