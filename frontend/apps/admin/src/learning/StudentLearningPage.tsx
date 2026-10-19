import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  MASTERY_LEVELS,
  MasteryHeatmap,
  SelectField,
  Spinner,
  TextField,
  TrendChart,
  type MasteryLevel,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { useLevelLabels } from "./hooks";
import { Empty, FormCard } from "./shared";

type Goal = components["schemas"]["Goal"];

/** One student's learning (E21): topic coverage heatmap, goals, score trend and homework
 * completion. */
export function StudentLearningPage({ studentId }: { studentId: string }) {
  const { t, i18n } = useTranslation();
  const levelLabels = useLevelLabels();
  const student = useQuery({
    queryKey: ["students", studentId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/students/{id}", { params: { path: { id: studentId } } })),
  });
  const coverage = useQuery({
    queryKey: ["learning", "coverage", studentId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/students/{student_id}/coverage", {
          params: { path: { student_id: studentId } },
        }),
      ),
  });
  const trend = useQuery({
    queryKey: ["learning", "trend", studentId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/students/{student_id}/trend", {
          params: { path: { student_id: studentId } },
        }),
      ),
  });
  const stats = useQuery({
    queryKey: ["learning", "stats", studentId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/homework-assignments/stats", {
          params: { query: { student: studentId } },
        }),
      ),
  });
  return (
    <section className="space-y-8">
      <h1 className="text-2xl font-semibold">
        {student.data
          ? t("learning.studentTitle", { name: student.data.full_name })
          : t("learning.title")}
      </h1>
      {stats.data ? (
        <p className="text-sm">
          {stats.data.completion_rate
            ? t("learning.homework.rate", {
                rate: stats.data.completion_rate,
                due: stats.data.due,
                overdue: stats.data.overdue,
              })
            : t("learning.homework.noneDue")}
        </p>
      ) : null}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t("learning.coverage.title")}</h2>
        {coverage.isLoading ? <Spinner label={t("grid.loading")} /> : null}
        {coverage.data && !coverage.data.length ? (
          <Empty>{t("learning.coverage.none")}</Empty>
        ) : null}
        {coverage.data?.map((c) => (
          <div key={c.curriculum.id} className="space-y-2">
            <h3 className="font-medium">
              {c.curriculum.name} ·{" "}
              {t("learning.coverage.covered", { covered: c.covered, total: c.topics })}
            </h3>
            <MasteryHeatmap
              units={c.units}
              levelLabels={levelLabels}
              legendLabel={t("learning.coverage.legend")}
              lessonsLabel={(count) => t("learning.coverage.lessons", { count })}
            />
            <MasteryForm studentId={studentId} units={c.units} />
          </div>
        ))}
      </section>
      <section className="space-y-3">
        <TrendChart
          points={trend.data ?? []}
          formatDate={(iso) => formatDate(iso, i18n.language)}
          labels={{
            title: t("learning.trend.title"),
            date: t("learning.assessments.date"),
            assessment: t("learning.assessments.name"),
            score: t("learning.assessments.score"),
            showTable: t("learning.trend.table"),
            empty: t("learning.trend.empty"),
          }}
        />
      </section>
      <GoalsSection studentId={studentId} />
    </section>
  );
}

function MasteryForm({
  studentId,
  units,
}: {
  studentId: string;
  units: components["schemas"]["CoverageUnit"][];
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const canEdit = usePermission("learning.mastery.edit");
  const levelLabels = useLevelLabels();
  const [node, setNode] = useState("");
  const [level, setLevel] = useState<MasteryLevel>("secure");
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/mastery", {
          body: { student: studentId, node, level },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["learning", "coverage", studentId] }),
  });
  if (!canEdit) return null;
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      aria-label={t("learning.coverage.setLevel")}
      onSubmit={(e) => {
        e.preventDefault();
        if (node) save.mutate();
      }}
    >
      <SelectField
        label={t("learning.coverage.topic")}
        value={node}
        onChange={(e) => setNode(e.target.value)}
        options={[
          { value: "", label: t("learning.coverage.chooseTopic") },
          ...units.flatMap((u) =>
            u.topics.map((x) => ({ value: x.id, label: `${u.name}: ${x.name}` })),
          ),
        ]}
      />
      <SelectField
        label={t("learning.coverage.level")}
        value={level}
        onChange={(e) => setLevel(e.target.value as MasteryLevel)}
        options={MASTERY_LEVELS.map((v) => ({ value: v, label: levelLabels[v] }))}
      />
      <Button type="submit" disabled={!node || save.isPending}>
        {t("learning.coverage.setLevel")}
      </Button>
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </form>
  );
}

function GoalsSection({ studentId }: { studentId: string }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const canManage = usePermission("learning.goal.manage");
  const goals = useQuery({
    queryKey: ["learning", "goals", studentId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/goals", {
          params: { query: { student: studentId, page_size: 100 } },
        }),
      ),
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["learning", "goals", studentId] });
  const [form, setForm] = useState({ title: "", target_grade: "", due_date: "", milestones: "" });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/goals", {
          body: {
            student: studentId,
            title: form.title,
            kind: form.target_grade ? "target_grade" : "custom",
            target_grade: form.target_grade,
            due_date: form.due_date || null,
            milestones: form.milestones
              .split(";")
              .map((m) => m.trim())
              .filter(Boolean)
              .map((title) => ({ title })),
          },
        }),
      ),
    onSuccess: () => {
      setForm({ title: "", target_grade: "", due_date: "", milestones: "" });
      void refresh();
    },
  });
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">{t("learning.goals.title")}</h2>
      {goals.data && !goals.data.results.length ? <Empty>{t("learning.goals.none")}</Empty> : null}
      {goals.data?.results.map((g) => (
        <GoalCard key={g.id} goal={g} canManage={canManage} onChange={refresh} />
      ))}
      {canManage ? (
        <FormCard
          title={t("learning.goals.new")}
          submit={t("learning.add")}
          pending={create.isPending}
          error={create.error}
          onSubmit={() => create.mutate()}
        >
          <TextField
            label={t("learning.goals.goal")}
            required
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
          <TextField
            label={t("learning.goals.target")}
            value={form.target_grade}
            onChange={(e) => setForm({ ...form, target_grade: e.target.value })}
          />
          <TextField
            label={t("learning.goals.due")}
            type="date"
            value={form.due_date}
            onChange={(e) => setForm({ ...form, due_date: e.target.value })}
          />
          <TextField
            label={t("learning.goals.milestones")}
            hint={t("learning.goals.milestonesHint")}
            value={form.milestones}
            onChange={(e) => setForm({ ...form, milestones: e.target.value })}
          />
        </FormCard>
      ) : null}
    </section>
  );
}

export function GoalCard({
  goal,
  canManage,
  onChange,
}: {
  goal: Goal;
  canManage: boolean;
  onChange: () => void;
}) {
  const { t, i18n } = useTranslation();
  const toggle = useMutation({
    mutationFn: async ({ milestone, done }: { milestone: string; done: boolean }) =>
      unwrap(
        await api.POST("/api/v1/learning/goals/{id}/milestone", {
          params: { path: { id: goal.id } },
          body: { milestone, done },
        }),
      ),
    onSuccess: onChange,
  });
  return (
    <article aria-label={goal.title} className="space-y-2 rounded-md border border-border p-3">
      <h3 className="font-medium">
        {goal.title}
        {goal.target_grade
          ? ` · ${t("learning.goals.targetIs", { grade: goal.target_grade })}`
          : ""}
      </h3>
      <p className="text-sm">
        {t(`learning.goals.statuses.${goal.status}`)}
        {goal.due_date ? ` · ${formatDate(goal.due_date, i18n.language)}` : ""}
      </p>
      <div
        role="progressbar"
        aria-label={t("learning.goals.progress")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={goal.progress_percent ?? 0}
        className="h-2 w-full max-w-sm rounded bg-muted"
      >
        <div className="h-2 rounded bg-brand" style={{ width: `${goal.progress_percent ?? 0}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">{goal.progress_percent ?? 0}%</p>
      {goal.milestones?.length ? (
        <ul className="space-y-1 text-sm">
          {goal.milestones.map((m) => (
            <li key={m.id}>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="size-5"
                  checked={Boolean(m.done)}
                  disabled={!canManage || toggle.isPending}
                  onChange={(e) =>
                    m.id && toggle.mutate({ milestone: m.id, done: e.target.checked })
                  }
                />
                {m.title}
              </label>
            </li>
          ))}
        </ul>
      ) : null}
      {toggle.error ? <Alert tone="danger">{toggle.error.message}</Alert> : null}
    </article>
  );
}
