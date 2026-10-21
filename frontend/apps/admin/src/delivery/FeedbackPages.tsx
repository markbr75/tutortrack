import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FigureStrip,
  PageHeader,
  Panel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useEffect, useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

type Feedback = components["schemas"]["LessonFeedback"];
type FeedbackStatus = Feedback["status"];

/** Five drawn stars, the given number filled in ink; the rest pale. */
function StarRow({ rating, className }: { rating: number; className?: string }) {
  return (
    <span aria-hidden="true" className={`inline-flex gap-0.5 ${className ?? ""}`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star
          key={n}
          strokeWidth={1.75}
          className={
            n <= rating ? "size-full fill-current text-foreground" : "size-full text-field"
          }
        />
      ))}
    </span>
  );
}

function Stars({ rating }: { rating: number | null }) {
  const { t } = useTranslation();
  if (rating === null) return <span className="text-muted-foreground">–</span>;
  return (
    <span role="img" aria-label={t("lessonFeedback.starsLabel", { count: rating })}>
      <StarRow rating={rating} className="h-3.5 [&>svg]:w-3.5" />
    </span>
  );
}

/** Feedback settings: the ``delivery.feedback_*`` org settings. */
function FeedbackSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("org.settings.manage");
  const area = useQuery({
    queryKey: ["settings", "delivery"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/settings/{area}", { params: { path: { area: "delivery" } } })),
  });
  const [values, setValues] = useState<Record<string, unknown>>({});
  useEffect(() => {
    if (area.data) setValues(area.data.values);
  }, [area.data]);
  const schema = (area.data?.schema ?? []).filter((d) => d.key.startsWith("delivery.feedback_"));
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/settings/{area}", {
          params: { path: { area: "delivery" } },
          body: { values: Object.fromEntries(schema.map((d) => [d.key, values[d.key]])) },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["settings", "delivery"], data),
  });
  const errors = fieldErrors(save.error);
  if (!area.data) return <Spinner label={t("grid.loading")} />;
  return (
    <Panel title={t("lessonFeedback.settings")} flush>
      <form
        aria-label={t("lessonFeedback.settings")}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="space-y-3 px-5 py-4">
          {schema.map((d) =>
            d.type === "bool" ? (
              <label key={d.key} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4"
                  disabled={!canManage}
                  checked={Boolean(values[d.key])}
                  onChange={(e) => setValues({ ...values, [d.key]: e.target.checked })}
                />
                {d.label}
              </label>
            ) : (
              <TextField
                key={d.key}
                label={d.label}
                type="number"
                disabled={!canManage}
                min={d.min_value}
                max={d.max_value}
                value={String(values[d.key] ?? "")}
                error={errors[d.key]}
                onChange={(e) => setValues({ ...values, [d.key]: Number(e.target.value) })}
              />
            ),
          )}
          <p className="text-xs text-muted-foreground">{t("lessonFeedback.consentNote")}</p>
          {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
        </div>
        {canManage ? (
          <div className="flex items-center justify-end gap-3 border-t border-border px-5 py-3">
            {save.isSuccess ? (
              <p role="status" className="text-sm text-muted-foreground">
                {t("common.saved")}
              </p>
            ) : null}
            <Button type="submit" size="sm" loading={save.isPending}>
              {t("common.save")}
            </Button>
          </div>
        ) : null}
      </form>
    </Panel>
  );
}

/** E09-T09: families' answers to post-lesson micro-surveys, with a per-tutor summary. */
export function LessonFeedbackPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("delivery.feedback.manage");
  const canSeeSettings = usePermission("org.settings.view");
  const [status, setStatus] = useState<FeedbackStatus | "">("");
  const [rating, setRating] = useState("");
  const query = { ...(status ? { status } : {}), ...(rating ? { rating } : {}) };
  const list = useQuery({
    queryKey: ["lesson-feedback", status, rating],
    queryFn: async () => unwrap(await api.GET("/api/v1/lesson-feedback", { params: { query } })),
  });
  const summary = useQuery({
    queryKey: ["lesson-feedback-summary", status, rating],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/lesson-feedback/summary", { params: { query } })),
  });
  const withdraw = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/lesson-feedback/{id}/withdraw", { params: { path: { id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["lesson-feedback"] }),
  });
  const rows: Feedback[] = list.data?.results ?? [];
  const s = summary.data;
  const low = s ? (s.stars["1"] ?? 0) + (s.stars["2"] ?? 0) : 0;
  return (
    <div>
      <PageHeader title={t("lessonFeedback.title")} />
      {s ? (
        <FigureStrip
          label={t("lessonFeedback.summary")}
          className="mb-6"
          figures={[
            { label: t("lessonFeedback.average"), value: s.average ?? "–" },
            {
              label: t("lessonFeedback.answered"),
              value: t("lessonFeedback.ofAsked", { answered: s.answered, asked: s.asked }),
            },
            { label: t("lessonFeedback.answerRate"), value: `${s.answer_rate}%` },
            { label: t("lessonFeedback.low"), value: low },
          ]}
        />
      ) : null}
      <div className="space-y-6">
        <div className="min-w-0">
          <form
            role="search"
            className="mb-4 flex flex-wrap items-center gap-2"
            aria-label={t("lessonFeedback.filters")}
            onSubmit={(e) => e.preventDefault()}
          >
            <SelectField
              label={t("lessonFeedback.status")}
              hideLabel
              size="sm"
              value={status}
              onChange={(e) => setStatus(e.target.value as FeedbackStatus | "")}
              options={[
                { value: "", label: t("designS5.feedback.anyStatus") },
                ...(["sent", "answered", "expired", "skipped"] as const).map((v) => ({
                  value: v,
                  label: t(`lessonFeedback.statuses.${v}`),
                })),
              ]}
            />
            <SelectField
              label={t("lessonFeedback.rating")}
              hideLabel
              size="sm"
              value={rating}
              onChange={(e) => setRating(e.target.value)}
              options={[
                { value: "", label: t("designS5.feedback.anyRating") },
                { value: "low", label: t("lessonFeedback.lowOnly") },
                ...["5", "4", "3", "2", "1"].map((v) => ({
                  value: v,
                  label: t("lessonFeedback.starsLabel", { count: Number(v) }),
                })),
              ]}
            />
          </form>
          {withdraw.error ? (
            <Alert tone="danger" className="mb-4">
              {withdraw.error.message}
            </Alert>
          ) : null}
          <div
            role="region"
            aria-label={t("lessonFeedback.title")}
            tabIndex={0}
            className="relative overflow-x-auto rounded-xl border border-border bg-surface"
          >
            <table className="w-full text-left text-sm [&_td]:px-4 [&_td]:py-2.5 [&_th]:px-4 [&_th]:py-2.5">
              <caption className="sr-only">{t("lessonFeedback.title")}</caption>
              <thead className="border-b border-border">
                <tr>
                  <th scope="col">{t("lessonFeedback.lesson")}</th>
                  <th scope="col" className="max-md:hidden">
                    {t("lessonFeedback.tutor")}
                  </th>
                  <th scope="col">{t("lessonFeedback.rating")}</th>
                  <th scope="col">{t("lessonFeedback.status")}</th>
                  {canManage ? (
                    <th scope="col">
                      <span className="sr-only">{t("common.actions")}</span>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {list.isLoading ? (
                  <tr>
                    <td colSpan={5}>
                      <Spinner label={t("grid.loading")} />
                    </td>
                  </tr>
                ) : null}
                {list.data && rows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-10! text-center text-muted-foreground">
                      {t("lessonFeedback.empty")}
                    </td>
                  </tr>
                ) : null}
                {rows.map((row) => (
                  <tr key={row.id} className="align-top">
                    <td className="min-w-56">
                      <span className="font-medium">{row.lesson_title}</span>
                      <span className="block text-xs text-muted-foreground tabular-nums">
                        {[formatDate(row.lesson_date), row.student.name].join(" · ")}
                        <span className="md:hidden">
                          {row.tutor?.name ? ` · ${row.tutor.name}` : ""}
                        </span>
                      </span>
                      {row.comment ? (
                        <p className="mt-1 max-w-prose whitespace-pre-wrap">{row.comment}</p>
                      ) : null}
                    </td>
                    <td className="max-md:hidden">{row.tutor?.name ?? ""}</td>
                    <td>
                      <Stars rating={row.rating} />
                    </td>
                    <td className="min-w-32">
                      {t(`lessonFeedback.statuses.${row.status}`)}
                      {row.skip_reason ? (
                        <span className="block text-xs text-muted-foreground">
                          {t(`lessonFeedback.skipReasons.${row.skip_reason}`)}
                        </span>
                      ) : null}
                    </td>
                    {canManage ? (
                      <td className="text-right">
                        {row.status === "sent" ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => withdraw.mutate(row.id)}
                            aria-label={t("lessonFeedback.withdrawFor", { name: row.student.name })}
                          >
                            {t("lessonFeedback.withdraw")}
                          </Button>
                        ) : null}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-2">
          {s && s.tutors.length ? (
            <Panel title={t("lessonFeedback.byTutor")} flush>
              <table className="w-full text-left text-sm [&_td]:px-5 [&_td]:py-2.5 [&_th]:px-5 [&_th]:py-2.5">
                <caption className="sr-only">{t("lessonFeedback.byTutor")}</caption>
                <thead className="border-b border-rule">
                  <tr>
                    <th scope="col">{t("lessonFeedback.tutor")}</th>
                    <th scope="col" className="text-right">
                      {t("lessonFeedback.average")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {s.tutors.map((row) => (
                    <tr key={row.tutor_id ?? "none"}>
                      <td>
                        <span className="font-medium">{row.tutor}</span>
                        <span className="block text-xs text-muted-foreground tabular-nums">
                          {t("designS5.feedback.answeredOf", {
                            answered: row.answered,
                            asked: row.asked,
                          })}
                        </span>
                      </td>
                      <td className="text-right font-semibold tabular-nums">{row.average}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          ) : null}
          {canSeeSettings ? <FeedbackSettings /> : null}
        </div>
      </div>
    </div>
  );
}

/** The family's one-question survey behind the emailed link (public). */
export function PublicFeedbackPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [stopAsking, setStopAsking] = useState(false);
  const item = useQuery({
    queryKey: ["public-feedback", token],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/public/lesson-feedback/{token}", { params: { path: { token } } }),
      ),
    retry: false,
  });
  const answer = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public/lesson-feedback/{token}", {
          params: { path: { token } },
          body: { rating, comment, stop_asking: stopAsking },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["public-feedback", token], data),
  });
  if (item.isError) {
    return <PublicLayout title={t("lessonFeedback.missing")}>{null}</PublicLayout>;
  }
  if (!item.data) return <Spinner label={t("grid.loading")} />;
  const f = item.data;
  const title = t("lessonFeedback.question", { student: f.student });
  if (f.status !== "sent") {
    return (
      <PublicLayout title={title} subtitle={f.organisation}>
        <p role="status">
          {f.status === "answered" ? t("lessonFeedback.thanks") : t("lessonFeedback.closed")}
        </p>
      </PublicLayout>
    );
  }
  return (
    <PublicLayout title={title} subtitle={f.organisation}>
      <p className="mb-6 text-muted-foreground">
        {f.tutor
          ? t("lessonFeedback.lessonWith", {
              lesson: f.lesson,
              tutor: f.tutor,
              date: formatDate(f.lesson_date),
            })
          : t("lessonFeedback.lessonOn", { lesson: f.lesson, date: formatDate(f.lesson_date) })}
      </p>
      <form
        className="space-y-5 rounded-xl border border-border bg-surface px-5 py-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (rating) answer.mutate();
        }}
      >
        <fieldset>
          <legend className="text-sm font-medium">{t("lessonFeedback.rateIt")}</legend>
          <div className="mt-2 grid grid-cols-5 gap-2">
            {[1, 2, 3, 4, 5].map((n) => (
              <label
                key={n}
                className="flex cursor-pointer flex-col items-center gap-1 rounded-md border border-field bg-surface px-1 py-2 hover:bg-muted has-[:checked]:border-foreground has-[:checked]:bg-muted has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-link"
              >
                <input
                  type="radio"
                  name="rating"
                  value={n}
                  className="sr-only"
                  aria-label={t("lessonFeedback.starsLabel", { count: n })}
                  checked={rating === n}
                  onChange={() => setRating(n)}
                />
                <Star
                  aria-hidden="true"
                  strokeWidth={1.75}
                  className={
                    n <= rating ? "size-5 fill-current text-foreground" : "size-5 text-field"
                  }
                />
                <span className="text-xs tabular-nums">
                  {t("lessonFeedback.starsLabel", { count: n })}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex flex-col gap-1">
          <label htmlFor="feedback-comment" className="text-sm font-medium">
            {t("lessonFeedback.commentOptional")}
          </label>
          <textarea
            id="feedback-comment"
            className="min-h-24 rounded-md border border-field bg-surface px-3 py-2 text-sm"
            maxLength={2000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1 size-4"
            checked={stopAsking}
            onChange={(e) => setStopAsking(e.target.checked)}
          />
          <span>{t("gapG6.stopAskingFeedback")}</span>
        </label>
        {!rating && answer.isIdle ? (
          <p className="text-xs text-muted-foreground">{t("lessonFeedback.chooseStars")}</p>
        ) : null}
        <Button type="submit" className="w-full sm:w-auto" disabled={!rating || answer.isPending}>
          {t("lessonFeedback.send")}
        </Button>
        {answer.error ? <Alert tone="danger">{answer.error.message}</Alert> : null}
      </form>
    </PublicLayout>
  );
}
