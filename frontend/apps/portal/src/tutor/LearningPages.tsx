import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  NamePlate,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import {
  PanelEmpty,
  PanelLoading,
  PortalHeader,
  TextAreaField,
  Word,
} from "../layout/PortalPage";

type Assignment = components["schemas"]["Assignment"];

function useMyStudents() {
  return useQuery({
    queryKey: ["tutor", "students"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/students")),
  });
}

/** Homework to review and new homework for my students (E21-T02 in the tutor app). While
 * hand-ins wait to be marked, the panel takes the margin-red rule and its count. */
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
  const waiting = toReview.data?.results ?? [];
  return (
    <div>
      <PortalHeader title={t("learning.tutor.homework")} />
      <div className="space-y-6">
        <RuledPanel
          title={t("learning.homework.toReview")}
          rule={waiting.length ? "margin" : "border"}
          aside={
            waiting.length ? (
              <span className="font-semibold text-margin tabular-nums">{waiting.length}</span>
            ) : undefined
          }
          flush
        >
          {toReview.isPending ? (
            <PanelLoading label={t("grid.loading")} />
          ) : waiting.length ? (
            <ul className="divide-y divide-rule">
              {waiting.map((a) => (
                <li key={a.id}>
                  <Link
                    to="/tutor/homework/$assignmentId"
                    params={{ assignmentId: a.id }}
                    className="flex min-h-12 items-center gap-3 px-5 py-2.5 text-sm hover:bg-muted/60"
                  >
                    <span className="flex-1 font-medium">
                      {a.homework_title} · {a.student_name}
                    </span>
                    <ChevronRight aria-hidden="true" className="size-4 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("learning.homework.nothingToReview")}</PanelEmpty>
          )}
        </RuledPanel>
        <SetHomework />
      </div>
    </div>
  );
}

function SetHomework() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const students = useMyStudents();
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
      aria-label={t("learning.homework.new")}
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <RuledPanel title={t("learning.homework.new")} flush>
        <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <TextField
              label={t("learning.homework.titleLabel")}
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </div>
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
            className="tabular-nums"
            type="datetime-local"
            required
            value={form.due}
            onChange={(e) => setForm({ ...form, due: e.target.value })}
          />
          <TextAreaField
            className="sm:col-span-2"
            label={t("learning.homework.instructions")}
            rows={4}
            value={form.instructions}
            onChange={(e) => setForm({ ...form, instructions: e.target.value })}
          />
        </div>
        {create.error ? (
          <div className="px-5 pb-4">
            <Alert tone="danger">{create.error.message}</Alert>
          </div>
        ) : null}
        <PanelFooter>
          <Button type="submit" disabled={create.isPending}>
            {t("learning.homework.setIt")}
          </Button>
          <span role="status" className="text-sm text-success">
            {create.isSuccess ? t("learning.tutor.homeworkSet") : ""}
          </span>
        </PanelFooter>
      </RuledPanel>
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
  if (assignment.isPending) return <Spinner label={t("grid.loading")} />;
  if (!assignment.data) return <Alert tone="danger">{t("errors.generic")}</Alert>;
  return <Review assignment={assignment.data} />;
}

function Review({ assignment }: { assignment: Assignment }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
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
    <article aria-label={assignment.homework_title}>
      <PortalHeader
        back={<Link to="/tutor/homework">{t("learning.tutor.homework")}</Link>}
        title={`${assignment.homework_title} · ${assignment.student_name}`}
        description={
          <Word
            tone={assignment.status === "submitted" ? "margin" : "ink"}
            className={assignment.status === "submitted" ? "" : "text-foreground"}
          >
            {t(`learning.portal.status.${assignment.status}`)}
          </Word>
        }
      />
      <div className="space-y-6">
        {assignment.submissions.length ? (
          <RuledPanel title={t("learning.portal.handedIn")} flush>
            <PanelRows>
              {assignment.submissions.map((s) => (
                <PanelRow key={s.id} className="space-y-1">
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {t("learning.homework.handedIn", {
                      when: formatDateTime(s.created_at, i18n.language),
                    })}
                    {s.is_late ? ` · ${t("learning.homework.late")}` : ""}
                  </p>
                  {s.body ? <p className="whitespace-pre-wrap">{s.body}</p> : null}
                  {s.link ? (
                    <a
                      className="break-all text-link underline-offset-2 hover:underline"
                      href={s.link}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {s.link}
                    </a>
                  ) : null}
                  {s.files.map((f) => (
                    <p key={f.id} className="text-xs">
                      {f.filename}
                    </p>
                  ))}
                </PanelRow>
              ))}
            </PanelRows>
          </RuledPanel>
        ) : null}
        {open ? (
          <form
            aria-label={t("learning.tutor.review")}
            onSubmit={(e) => {
              e.preventDefault();
              review.mutate("complete");
            }}
          >
            <RuledPanel title={t("learning.tutor.review")} flush>
              <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-[10rem_minmax(0,1fr)]">
                <TextField
                  label={t("learning.homework.grade")}
                  value={grade}
                  onChange={(e) => setGrade(e.target.value)}
                />
                <TextAreaField
                  label={t("learning.homework.feedback")}
                  rows={4}
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                />
              </div>
              {review.error ? (
                <div className="px-5 pb-4">
                  <Alert tone="danger">{review.error.message}</Alert>
                </div>
              ) : null}
              <PanelFooter>
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
                <Button type="submit" disabled={review.isPending}>
                  {t("learning.homework.markComplete")}
                </Button>
                <span role="status" className="text-sm text-success">
                  {review.isSuccess ? t("learning.tutor.reviewed") : ""}
                </span>
              </PanelFooter>
            </RuledPanel>
          </form>
        ) : null}
      </div>
    </article>
  );
}

/** My resource library: add links and share them with my students (E21-T01). Each
 * resource is a name plate with a compact share row under it. */
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
  const rows = resources.data?.results ?? [];
  return (
    <div>
      <PortalHeader title={t("learning.tutor.resources")} />
      <div className="space-y-6">
        <RuledPanel label={t("learning.tutor.resources")} flush>
          {resources.isPending ? (
            <PanelLoading label={t("grid.loading")} />
          ) : rows.length ? (
            <PanelRows>
              {rows.map((r) => (
                <PanelRow key={r.id} className="space-y-2">
                  <NamePlate
                    name={r.title}
                    context={`${t(`learning.resources.media.${r.media_type}`)} · ${
                      r.owner_name || t("learning.resources.orgLibrary")
                    }`}
                  />
                  <form
                    className="flex flex-wrap items-end gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (target[r.id]) share.mutate(r.id);
                    }}
                  >
                    <SelectField
                      size="sm"
                      hideLabel
                      label={t("learning.resources.shareWith", { title: r.title })}
                      value={target[r.id] ?? ""}
                      onChange={(e) => setTarget({ ...target, [r.id]: e.target.value })}
                      options={options}
                    />
                    <Button
                      type="submit"
                      size="sm"
                      variant="secondary"
                      className="h-9"
                      disabled={!target[r.id] || share.isPending}
                    >
                      {t("learning.resources.share")}
                      <span className="sr-only"> {r.title}</span>
                    </Button>
                  </form>
                </PanelRow>
              ))}
            </PanelRows>
          ) : (
            <PanelEmpty>{t("designS10.noResources")}</PanelEmpty>
          )}
          {share.error ? (
            <div className="px-5 pb-4">
              <Alert tone="danger">{share.error.message}</Alert>
            </div>
          ) : null}
          {share.isSuccess ? (
            <p role="status" className="px-5 pb-4 text-sm text-success">
              {t("learning.tutor.shared")}
            </p>
          ) : null}
        </RuledPanel>
        <form
          aria-label={t("learning.resources.new")}
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <RuledPanel title={t("learning.resources.new")} flush>
            <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
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
            </div>
            {add.error ? (
              <div className="px-5 pb-4">
                <Alert tone="danger">{add.error.message}</Alert>
              </div>
            ) : null}
            <PanelFooter>
              <Button type="submit" disabled={add.isPending}>
                {t("learning.add")}
              </Button>
            </PanelFooter>
          </RuledPanel>
        </form>
      </div>
    </div>
  );
}
