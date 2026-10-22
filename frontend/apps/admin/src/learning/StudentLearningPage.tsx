import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  MASTERY_LEVELS,
  MasteryHeatmap,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  TextField,
  TrendChart,
  type MasteryLevel,
} from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { useLevelLabels } from "./hooks";
import { PanelLoading } from "../billing/moneyUi";
import { BackSeparator, RecordHeader, RecordLayout } from "../components/RecordHeader";
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
  const main = (
    <>
      {coverage.isPending ? (
        <RuledPanel title={t("learning.coverage.title")}>
          <PanelLoading label={t("grid.loading")} />
        </RuledPanel>
      ) : null}
      {coverage.data && !coverage.data.length ? (
        <RuledPanel flush title={t("learning.coverage.title")}>
          <Empty>{t("learning.coverage.none")}</Empty>
        </RuledPanel>
      ) : null}
      {coverage.data?.map((c) => (
        <RuledPanel
          key={c.curriculum.id}
          title={c.curriculum.name}
          description={t("learning.coverage.title")}
          aside={
            <span className="text-muted-foreground tabular-nums">
              {t("learning.coverage.covered", { covered: c.covered, total: c.topics })}
            </span>
          }
          footer={<MasteryForm studentId={studentId} units={c.units} />}
        >
          <MasteryHeatmap
            units={c.units}
            levelLabels={levelLabels}
            legendLabel={t("learning.coverage.legend")}
            lessonsLabel={(count) => t("learning.coverage.lessons", { count })}
          />
        </RuledPanel>
      ))}
      <RuledPanel title={t("learning.trend.title")}>
        <TrendChart
          points={trend.data ?? []}
          formatDate={(iso) => formatDate(iso, i18n.language)}
          hideTitle
          labels={{
            title: t("learning.trend.title"),
            date: t("learning.assessments.date"),
            assessment: t("learning.assessments.name"),
            score: t("learning.assessments.score"),
            showTable: t("learning.trend.table"),
            empty: t("learning.trend.empty"),
          }}
        />
      </RuledPanel>
    </>
  );
  return (
    <section>
      <RecordHeader
        back={
          <>
            <Link to="/learning">{t("learning.title")}</Link>
            {student.data ? (
              <>
                <BackSeparator />
                <Link to="/students/$studentId" params={{ studentId }}>
                  {student.data.full_name}
                </Link>
              </>
            ) : null}
          </>
        }
        title={
          student.data
            ? t("learning.studentTitle", { name: student.data.full_name })
            : t("learning.title")
        }
        description={
          stats.data
            ? stats.data.completion_rate
              ? t("learning.homework.rate", {
                  rate: stats.data.completion_rate,
                  due: stats.data.due,
                  overdue: stats.data.overdue,
                })
              : t("learning.homework.noneDue")
            : undefined
        }
      />
      <RecordLayout main={main} side={<GoalsSection studentId={studentId} />} />
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
      className="flex w-full flex-wrap items-end gap-2"
      aria-label={t("learning.coverage.setLevel")}
      onSubmit={(e) => {
        e.preventDefault();
        if (node) save.mutate();
      }}
    >
      <div className="min-w-56 flex-1 sm:max-w-sm">
        <SelectField
          label={t("learning.coverage.topic")}
          size="sm"
          value={node}
          onChange={(e) => setNode(e.target.value)}
          options={[
            { value: "", label: t("learning.coverage.chooseTopic") },
            ...units.flatMap((u) =>
              u.topics.map((x) => ({ value: x.id, label: `${u.name}: ${x.name}` })),
            ),
          ]}
        />
      </div>
      <SelectField
        label={t("learning.coverage.level")}
        size="sm"
        value={level}
        onChange={(e) => setLevel(e.target.value as MasteryLevel)}
        options={MASTERY_LEVELS.map((v) => ({ value: v, label: levelLabels[v] }))}
      />
      <Button
        type="submit"
        size="sm"
        variant="secondary"
        className="h-9"
        disabled={!node}
        loading={save.isPending}
      >
        {t("learning.coverage.setLevel")}
      </Button>
      {save.error ? (
        <Alert tone="danger" className="w-full">
          {save.error.message}
        </Alert>
      ) : null}
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
  const list = goals.data?.results ?? [];
  return (
    <>
      <RuledPanel flush title={t("learning.goals.title")}>
        {goals.isPending ? (
          <PanelLoading label={t("grid.loading")} />
        ) : !list.length ? (
          <Empty>{t("learning.goals.none")}</Empty>
        ) : (
          <PanelRows>
            {list.map((g) => (
              <PanelRow key={g.id}>
                <GoalCard goal={g} canManage={canManage} onChange={refresh} />
              </PanelRow>
            ))}
          </PanelRows>
        )}
      </RuledPanel>
      {canManage ? (
        <FormCard
          title={t("learning.goals.new")}
          submit={t("learning.add")}
          pending={create.isPending}
          error={create.error}
          onSubmit={() => create.mutate()}
          columns={1}
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
    </>
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
  const milestones = goal.milestones ?? [];
  const done = milestones.filter((m) => m.done).length;
  return (
    <article aria-label={goal.title} className="space-y-2">
      <div>
        <h3 className="font-medium">
          {goal.title}
          {goal.target_grade
            ? ` · ${t("learning.goals.targetIs", { grade: goal.target_grade })}`
            : ""}
        </h3>
        <p className="text-xs text-muted-foreground tabular-nums">
          {[
            t(`learning.goals.statuses.${goal.status}`),
            t("designS6.learning.progressDone", { percent: goal.progress_percent ?? 0 }),
            milestones.length
              ? t("designS6.learning.milestonesDone", { done, total: milestones.length })
              : "",
            goal.due_date ? formatDate(goal.due_date, i18n.language) : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      {milestones.length ? (
        <ul className="space-y-1.5 text-sm">
          {milestones.map((m) => (
            <li key={m.id}>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={Boolean(m.done)}
                  disabled={!canManage || toggle.isPending}
                  onChange={(e) =>
                    m.id && toggle.mutate({ milestone: m.id, done: e.target.checked })
                  }
                />
                <span className={m.done ? "text-muted-foreground line-through" : undefined}>
                  {m.title}
                </span>
              </label>
            </li>
          ))}
        </ul>
      ) : null}
      {toggle.error ? <Alert tone="danger">{toggle.error.message}</Alert> : null}
    </article>
  );
}
