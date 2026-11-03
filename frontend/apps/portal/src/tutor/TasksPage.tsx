import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { api, uploadFile } from "../api";
import { SignForm } from "../esign/SignForm";
import { FileField, PanelEmpty, PortalHeader, Word } from "../layout/PortalPage";

type Task = components["schemas"]["MyPathwayTask"];
type Payload = components["schemas"]["PathwayCompleteStepRequest"];
type Field = {
  key: string;
  label: string;
  type: string;
  required?: boolean;
  help?: string;
  options?: string[];
};
type View = Record<string, unknown>;

const TASKS = ["tutor", "tasks"];

/** The tutor's Tasks (E34 FR-34-1): every pathway step waiting for them, one ruled panel
 * per pathway, each step doing its work in place; then calls they booked that are still to
 * come. */
export function TasksPage() {
  const { t } = useTranslation();
  const tasks = useQuery({
    queryKey: TASKS,
    queryFn: async () => unwrap(await api.GET("/api/v1/me/tasks")),
  });
  if (!tasks.data) return <Spinner label={t("grid.loading")} />;
  const todo = tasks.data.filter((task) => task.status !== "done");
  const calls = tasks.data.filter((task) => task.status === "done");
  const pathways = [...new Set(todo.map((task) => task.pathway))];
  return (
    <div>
      <PortalHeader title={t("pathways.tasks.title")} />
      <div className="space-y-6">
        {!todo.length ? (
          <RuledPanel label={t("pathways.tasks.title")}>
            <PanelEmpty>{t("pathways.tasks.none")}</PanelEmpty>
          </RuledPanel>
        ) : null}
        {pathways.map((pathway) => (
          <RuledPanel key={pathway} title={pathway} flush>
            <ul className="divide-y divide-rule">
              {todo
                .filter((task) => task.pathway === pathway)
                .map((task) => (
                  <TaskRow key={task.id} task={task} />
                ))}
            </ul>
          </RuledPanel>
        ))}
        {calls.length ? <BookedCalls calls={calls} /> : null}
      </div>
    </div>
  );
}

function TaskRow({ task }: { task: Task }) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const view = (task.view ?? {}) as View;
  const waiting = task.status === "review";
  const startLabel = t(`pathways.tasks.start.${task.step_type}`, {
    defaultValue: t("pathways.tasks.do"),
  });
  const auto =
    task.step_type === "show_check" && !view.requirement
      ? "checks"
      : task.step_type === "trial_lesson"
        ? "auto"
        : null;
  return (
    <li className="px-5 py-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <p className="font-medium">{task.name}</p>
          <p className="text-xs text-muted-foreground tabular-nums">
            {task.due_at
              ? t("pathways.tasks.due", { when: formatDateTime(task.due_at, i18n.language) })
              : t("pathways.tasks.noDue")}
          </p>
          {task.reason && !waiting ? (
            <p className="mt-1 text-xs text-danger">
              {t("pathways.tasks.sentBack", { reason: task.reason })}
            </p>
          ) : null}
        </div>
        {waiting ? (
          <Word tone="muted">{t("pathways.tasks.waiting")}</Word>
        ) : auto ? null : !open ? (
          <Button
            size="sm"
            aria-label={`${startLabel}: ${task.name}`}
            onClick={() => setOpen(true)}
          >
            {startLabel}
          </Button>
        ) : null}
      </div>
      {auto === "checks" ? (
        <p className="mt-2 text-sm text-muted-foreground">
          {(view.missing as string[] | undefined)?.length
            ? t("pathways.tasks.missingChecks", {
                checks: (view.missing as string[]).join(", "),
              })
            : t("pathways.tasks.checksTick")}{" "}
          <Link
            to="/tutor/compliance"
            className="font-medium text-link underline-offset-2 hover:underline"
          >
            {t("pathways.tasks.openChecks")}
          </Link>
        </p>
      ) : null}
      {auto === "auto" ? (
        <p className="mt-2 text-sm text-muted-foreground">{t("pathways.tasks.trialTick")}</p>
      ) : null}
      {open && !waiting && !auto ? (
        <div className="mt-3">
          <TaskForm task={task} view={view} onClose={() => setOpen(false)} />
        </div>
      ) : null}
    </li>
  );
}

function useComplete(task: Task, onDone: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: Payload) =>
      unwrap(
        await api.POST("/api/v1/me/tasks/{id}/complete", {
          params: { path: { id: task.id } },
          body,
        }),
      ),
    onSuccess: () => {
      onDone();
      void queryClient.invalidateQueries({ queryKey: TASKS });
    },
  });
}

function TaskForm({ task, view, onClose }: { task: Task; view: View; onClose: () => void }) {
  const { t } = useTranslation();
  const complete = useComplete(task, onClose);
  const error = complete.error ? <Alert tone="danger">{complete.error.message}</Alert> : null;
  switch (task.step_type) {
    case "sign":
      return (
        <div>
          <p className="whitespace-pre-line rounded-md border border-rule bg-background p-3 text-sm">
            {String(view.text ?? "")}
          </p>
          <SignForm
            title={String(view.title ?? task.name)}
            pending={complete.isPending}
            error={complete.error?.message}
            onSign={(name) => complete.mutate({ full_name: name })}
            onCancel={onClose}
          />
        </div>
      );
    case "acknowledge":
      return (
        <div className="space-y-3">
          {view.text ? <p className="whitespace-pre-line">{String(view.text)}</p> : null}
          {view.link ? (
            <a
              className="font-medium text-link underline-offset-2 hover:underline"
              href={String(view.link)}
              target="_blank"
              rel="noreferrer"
            >
              {t("pathways.tasks.openDocument", { title: String(view.title ?? task.name) })}
            </a>
          ) : null}
          {error}
          <div className="flex gap-2">
            <Button size="sm" disabled={complete.isPending} onClick={() => complete.mutate({})}>
              {t("pathways.tasks.read")}
            </Button>
            <Button size="sm" variant="ghost" onClick={onClose}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      );
    case "questions":
      return (
        <QuestionsForm
          fields={(view.fields as Field[]) ?? []}
          pending={complete.isPending}
          error={error}
          onSubmit={(answers) => complete.mutate({ answers })}
          onCancel={onClose}
        />
      );
    case "upload":
      return (
        <FilesForm
          label={t("pathways.tasks.files")}
          instructions={String(view.instructions ?? "")}
          multiple={Number(view.max_files ?? 1) > 1}
          pending={complete.isPending}
          error={error}
          onSubmit={(files) => complete.mutate({ files })}
          onCancel={onClose}
        />
      );
    case "show_check":
      return <CheckForm view={view} complete={complete} error={error} onCancel={onClose} />;
    case "book_call":
      return <CallForm view={view} complete={complete} error={error} onCancel={onClose} />;
    default:
      return <Alert tone="info">{t("pathways.tasks.elsewhere")}</Alert>;
  }
}

function Actions({
  pending,
  onCancel,
  label,
}: {
  pending: boolean;
  onCancel: () => void;
  label: string;
}) {
  const { t } = useTranslation();
  return (
    <PanelFooter>
      <Button type="submit" size="sm" disabled={pending}>
        {label}
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
        {t("common.cancel")}
      </Button>
    </PanelFooter>
  );
}

function QuestionsForm({
  fields,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  fields: Field[];
  pending: boolean;
  error: React.ReactNode;
  onSubmit: (answers: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const set = (key: string, value: unknown) => setAnswers((a) => ({ ...a, [key]: value }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit(answers);
  };
  return (
    <form className="space-y-3" onSubmit={submit}>
      {fields.map((f) => {
        const common = { label: f.label, hint: f.help, required: f.required };
        if (f.type === "textarea") {
          return (
            <TextAreaField
              key={f.key}
              {...common}
              rows={3}
              value={String(answers[f.key] ?? "")}
              onChange={(e) => set(f.key, e.target.value)}
            />
          );
        }
        if (f.type === "select") {
          return (
            <SelectField
              key={f.key}
              {...common}
              value={String(answers[f.key] ?? "")}
              options={[
                { value: "", label: t("pathways.tasks.choose") },
                ...(f.options ?? []).map((o) => ({ value: o, label: o })),
              ]}
              onChange={(e) => set(f.key, e.target.value)}
            />
          );
        }
        if (f.type === "multiselect" || f.type === "checkbox") {
          const options = f.type === "checkbox" ? [f.label] : (f.options ?? []);
          const chosen = (answers[f.key] as string[] | boolean | undefined) ?? [];
          return (
            <fieldset key={f.key} className="space-y-1">
              {f.type === "multiselect" ? (
                <legend className="text-sm font-medium">{f.label}</legend>
              ) : null}
              {options.map((o) => (
                <CheckboxField
                  key={o}
                  label={o}
                  checked={
                    f.type === "checkbox" ? Boolean(chosen) : (chosen as string[]).includes(o)
                  }
                  onChange={(e) =>
                    f.type === "checkbox"
                      ? set(f.key, e.target.checked)
                      : set(
                          f.key,
                          e.target.checked
                            ? [...(chosen as string[]), o]
                            : (chosen as string[]).filter((x) => x !== o),
                        )
                  }
                />
              ))}
            </fieldset>
          );
        }
        const type = { phone: "tel", number: "number", date: "date", email: "email" }[f.type];
        return (
          <TextField
            key={f.key}
            {...common}
            type={type ?? "text"}
            className={type === "number" || type === "date" ? "tabular-nums" : undefined}
            value={String(answers[f.key] ?? "")}
            onChange={(e) =>
              set(
                f.key,
                f.type === "number" && e.target.value ? Number(e.target.value) : e.target.value,
              )
            }
          />
        );
      })}
      {error}
      <Actions pending={pending} onCancel={onCancel} label={t("pathways.tasks.send")} />
    </form>
  );
}

function FilesForm({
  label,
  instructions,
  multiple,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  label: string;
  instructions: string;
  multiple: boolean;
  pending: boolean;
  error: React.ReactNode;
  onSubmit: (files: string[]) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setUploading(true);
        try {
          onSubmit(await Promise.all(files.map((f) => uploadFile(f))));
        } finally {
          setUploading(false);
        }
      }}
    >
      {instructions ? <p className="whitespace-pre-line">{instructions}</p> : null}
      <FileField
        label={label}
        multiple={multiple}
        accept="image/*,application/pdf"
        onChange={(e) => setFiles([...(e.target.files ?? [])])}
      />
      {error}
      <Actions
        pending={pending || uploading || !files.length}
        onCancel={onCancel}
        label={t("pathways.tasks.send")}
      />
    </form>
  );
}

function CheckForm({
  view,
  complete,
  error,
  onCancel,
}: {
  view: View;
  complete: ReturnType<typeof useComplete>;
  error: React.ReactNode;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [number, setNumber] = useState("");
  const [issue, setIssue] = useState("");
  const [expiry, setExpiry] = useState("");
  const [file, setFile] = useState<File | null>(null);
  return (
    <form
      className="space-y-3"
      aria-label={String(view.name ?? "")}
      onSubmit={async (e) => {
        e.preventDefault();
        const files = file ? [await uploadFile(file)] : [];
        complete.mutate({
          number,
          issue_date: issue || null,
          expiry_date: expiry || null,
          files,
        });
      }}
    >
      <div className="grid items-start gap-3 sm:grid-cols-2">
        {view.has_number ? (
          <TextField
            label={t("onboard.number")}
            className="tabular-nums"
            value={number}
            onChange={(e) => setNumber(e.target.value)}
          />
        ) : null}
        <TextField
          label={t("onboard.issueDate")}
          type="date"
          className="tabular-nums"
          value={issue}
          onChange={(e) => setIssue(e.target.value)}
        />
        {view.has_expiry ? (
          <TextField
            label={t("onboard.expiryDate")}
            type="date"
            className="tabular-nums"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
          />
        ) : null}
        <FileField
          label={t("onboard.file")}
          accept="image/*,application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </div>
      {error}
      <Actions pending={complete.isPending} onCancel={onCancel} label={t("onboard.upload")} />
    </form>
  );
}

function CallForm({
  view,
  complete,
  error,
  onCancel,
}: {
  view: View;
  complete: ReturnType<typeof useComplete>;
  error: React.ReactNode;
  onCancel: () => void;
}) {
  const { t, i18n } = useTranslation();
  const slots = (view.slots as string[] | undefined) ?? [];
  const [start, setStart] = useState(slots[0] ?? "");
  if (!slots.length) return <Alert tone="info">{t("pathways.tasks.noSlots")}</Alert>;
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        complete.mutate({ start });
      }}
    >
      <p>
        {t("pathways.tasks.callWith", {
          minutes: Number(view.minutes ?? 30),
          host: String(view.host ?? ""),
        })}
      </p>
      <SelectField
        label={t("pathways.tasks.time")}
        value={start}
        options={slots.map((s) => ({ value: s, label: formatDateTime(s, i18n.language) }))}
        onChange={(e) => setStart(e.target.value)}
      />
      {error}
      <Actions
        pending={complete.isPending || !start}
        onCancel={onCancel}
        label={t("pathways.tasks.book")}
      />
    </form>
  );
}

function BookedCalls({ calls }: { calls: Task[] }) {
  const { t, i18n } = useTranslation();
  return (
    <RuledPanel title={t("pathways.tasks.calls")} flush>
      <ul className="divide-y divide-rule">
        {calls.map((call) => {
          const result = (call.result ?? {}) as Record<string, unknown>;
          return (
            <li
              key={call.id}
              className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm"
            >
              <span>
                <span className="font-medium">{call.name}</span>
                <span className="block text-xs text-muted-foreground tabular-nums">
                  {formatDateTime(String(result.start), i18n.language)} · {call.pathway}
                </span>
              </span>
              {result.meeting_url ? (
                <a
                  className="font-medium text-link underline-offset-2 hover:underline"
                  href={String(result.meeting_url)}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`${t("pathways.tasks.join")}: ${call.name}`}
                >
                  {t("pathways.tasks.join")}
                </a>
              ) : (
                <Word tone="muted">{t("pathways.tasks.linkSoon")}</Word>
              )}
            </li>
          );
        })}
      </ul>
    </RuledPanel>
  );
}
