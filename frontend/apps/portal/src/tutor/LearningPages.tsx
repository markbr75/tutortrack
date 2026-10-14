import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";

import { api } from "../api";

type Assignment = components["schemas"]["Assignment"];

function useMyStudents() {
  return useQuery({
    queryKey: ["tutor", "students"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/students")),
  });
}

/** Homework to review and new homework for my students (E21-T02 in the tutor app). */
export function TutorHomeworkPage() {
  const { t } = useTranslation();
  const toReview = useQuery({
    queryKey: ["tutor", "learning", "review"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/homework-assignments", {
          params: { query: { status: ["submitted"], page_size: 100 } },
        }),
      ),
  });
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("learning.tutor.homework")}</h1>
      <h2 className="font-semibold">{t("learning.homework.toReview")}</h2>
      {toReview.isPending ? <Spinner className="size-6" label={t("grid.loading")} /> : null}
      {toReview.data && !toReview.data.results.length ? (
        <p className="text-sm text-muted-foreground">{t("learning.homework.nothingToReview")}</p>
      ) : null}
      <ul className="space-y-2">
        {toReview.data?.results.map((a) => (
          <li key={a.id} className="rounded-lg border border-border p-3">
            <Link
              to="/tutor/homework/$assignmentId"
              params={{ assignmentId: a.id }}
              className="font-medium underline"
            >
              {a.homework_title} · {a.student_name}
            </Link>
          </li>
        ))}
      </ul>
      <SetHomework />
    </div>
  );
}

function SetHomework() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const students = useMyStudents();
  const instructionsId = useId();
  const [form, setForm] = useState({ title: "", student: "", due: "", instructions: "" });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/homework", {
          body: {
            title: form.title,
            students: [form.student],
            due_at: new Date(form.due).toISOString(),
            instructions: form.instructions,
            submission_type: "text",
          },
        }),
      ),
    onSuccess: () => {
      setForm({ title: "", student: "", due: "", instructions: "" });
      void queryClient.invalidateQueries({ queryKey: ["tutor", "learning"] });
    },
  });
  return (
    <form
      className="space-y-3 rounded-lg border border-border p-4"
      aria-label={t("learning.homework.new")}
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <h2 className="font-semibold">{t("learning.homework.new")}</h2>
      <TextField
        label={t("learning.homework.titleLabel")}
        required
        value={form.title}
        onChange={(e) => setForm({ ...form, title: e.target.value })}
      />
      <SelectField
        label={t("learning.student")}
        required
        value={form.student}
        onChange={(e) => setForm({ ...form, student: e.target.value })}
        options={[
          { value: "", label: t("learning.chooseStudent") },
          ...(students.data ?? []).map((s) => ({ value: s.id, label: s.name })),
        ]}
      />
      <TextField
        label={t("learning.homework.due")}
        type="datetime-local"
        required
        value={form.due}
        onChange={(e) => setForm({ ...form, due: e.target.value })}
      />
      <div className="space-y-1">
        <label htmlFor={instructionsId} className="text-sm font-medium">
          {t("learning.homework.instructions")}
        </label>
        <textarea
          id={instructionsId}
          className="min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 text-base"
          value={form.instructions}
          onChange={(e) => setForm({ ...form, instructions: e.target.value })}
        />
      </div>
      {create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
      {create.isSuccess ? <p role="status">{t("learning.tutor.homeworkSet")}</p> : null}
      <Button type="submit" disabled={create.isPending}>
        {t("learning.homework.setIt")}
      </Button>
    </form>
  );
}

/** Review one hand-in: grade and feedback, or send it back. */
export function TutorReviewPage({ assignmentId }: { assignmentId: string }) {
  const { t } = useTranslation();
  const assignment = useQuery({
    queryKey: ["tutor", "learning", "assignment", assignmentId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/homework-assignments/{id}", {
          params: { path: { id: assignmentId } },
        }),
      ),
  });
  if (assignment.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  if (!assignment.data) return <p>{t("errors.generic")}</p>;
  return <Review assignment={assignment.data} />;
}

function Review({ assignment }: { assignment: Assignment }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const feedbackId = useId();
  const [grade, setGrade] = useState(assignment.grade);
  const [feedback, setFeedback] = useState(assignment.feedback);
  const review = useMutation({
    mutationFn: async (outcome: "complete" | "resubmit") =>
      unwrap(
        await api.POST("/api/v1/learning/homework-assignments/{id}/review", {
          params: { path: { id: assignment.id } },
          body: { outcome, grade, feedback },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tutor", "learning"] }),
  });
  const open = assignment.status === "submitted" || assignment.status === "assigned";
  return (
    <article className="space-y-4" aria-label={assignment.homework_title}>
      <h1 className="text-xl font-semibold">
        {assignment.homework_title} · {assignment.student_name}
      </h1>
      <p className="text-sm">{t(`learning.portal.status.${assignment.status}`)}</p>
      {assignment.submissions.map((s) => (
        <section key={s.id} className="rounded-lg border border-border p-3 text-sm">
          <p className="text-muted-foreground">
            {t("learning.homework.handedIn", { when: formatDateTime(s.created_at, i18n.language) })}
            {s.is_late ? ` · ${t("learning.homework.late")}` : ""}
          </p>
          {s.body ? <p className="whitespace-pre-wrap">{s.body}</p> : null}
          {s.link ? (
            <a className="underline" href={s.link} target="_blank" rel="noreferrer noopener">
              {s.link}
            </a>
          ) : null}
          {s.files.map((f) => (
            <p key={f.id}>{f.filename}</p>
          ))}
        </section>
      ))}
      {open ? (
        <form
          className="space-y-3"
          aria-label={t("learning.tutor.review")}
          onSubmit={(e) => {
            e.preventDefault();
            review.mutate("complete");
          }}
        >
          <TextField
            label={t("learning.homework.grade")}
            value={grade}
            onChange={(e) => setGrade(e.target.value)}
          />
          <div className="space-y-1">
            <label htmlFor={feedbackId} className="text-sm font-medium">
              {t("learning.homework.feedback")}
            </label>
            <textarea
              id={feedbackId}
              className="min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 text-base"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
            />
          </div>
          {review.error ? <Alert tone="danger">{review.error.message}</Alert> : null}
          {review.isSuccess ? <p role="status">{t("learning.tutor.reviewed")}</p> : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={review.isPending}>
              {t("learning.homework.markComplete")}
            </Button>
            {assignment.status === "submitted" ? (
              <Button
                type="button"
                variant="secondary"
                disabled={review.isPending}
                onClick={() => review.mutate("resubmit")}
              >
                {t("learning.homework.returnIt")}
              </Button>
            ) : null}
          </div>
        </form>
      ) : null}
    </article>
  );
}

/** My resource library: add links and share them with my students (E21-T01). */
export function TutorResourcesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const students = useMyStudents();
  const resources = useQuery({
    queryKey: ["tutor", "learning", "resources"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/resources", {
          params: { query: { archived: false, page_size: 100 } },
        }),
      ),
  });
  const [form, setForm] = useState({ title: "", url: "" });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/resources", {
          body: { title: form.title, url: form.url, kind: "link" },
        }),
      ),
    onSuccess: () => {
      setForm({ title: "", url: "" });
      void queryClient.invalidateQueries({ queryKey: ["tutor", "learning", "resources"] });
    },
  });
  const [target, setTarget] = useState<Record<string, string>>({});
  const share = useMutation({
    mutationFn: async (resource: string) =>
      unwrap(
        await api.POST("/api/v1/learning/resources/{id}/share", {
          params: { path: { id: resource } },
          body: { students: [target[resource] ?? ""] },
        }),
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["tutor", "learning", "resources"] }),
  });
  const options = [
    { value: "", label: t("learning.chooseStudent") },
    ...(students.data ?? []).map((s) => ({ value: s.id, label: s.name })),
  ];
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("learning.tutor.resources")}</h1>
      {resources.isPending ? <Spinner className="size-6" label={t("grid.loading")} /> : null}
      <ul className="space-y-2">
        {resources.data?.results.map((r) => (
          <li key={r.id} className="space-y-2 rounded-lg border border-border p-3">
            <p className="font-medium">{r.title}</p>
            <p className="text-sm text-muted-foreground">
              {t(`learning.resources.media.${r.media_type}`)} ·{" "}
              {r.owner_name || t("learning.resources.orgLibrary")}
            </p>
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (target[r.id]) share.mutate(r.id);
              }}
            >
              <SelectField
                label={t("learning.resources.shareWith", { title: r.title })}
                value={target[r.id] ?? ""}
                onChange={(e) => setTarget({ ...target, [r.id]: e.target.value })}
                options={options}
              />
              <Button type="submit" size="sm" disabled={!target[r.id] || share.isPending}>
                {t("learning.resources.share")}
              </Button>
            </form>
          </li>
        ))}
      </ul>
      {share.error ? <Alert tone="danger">{share.error.message}</Alert> : null}
      {share.isSuccess ? <p role="status">{t("learning.tutor.shared")}</p> : null}
      <form
        className="space-y-3 rounded-lg border border-border p-4"
        aria-label={t("learning.resources.new")}
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <h2 className="font-semibold">{t("learning.resources.new")}</h2>
        <TextField
          label={t("learning.resources.titleLabel")}
          required
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
        <TextField
          label={t("learning.resources.url")}
          type="url"
          required
          value={form.url}
          onChange={(e) => setForm({ ...form, url: e.target.value })}
        />
        {add.error ? <Alert tone="danger">{add.error.message}</Alert> : null}
        <Button type="submit" disabled={add.isPending}>
          {t("learning.add")}
        </Button>
      </form>
    </div>
  );
}
