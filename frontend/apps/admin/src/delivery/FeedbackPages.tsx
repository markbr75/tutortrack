import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

type Feedback = components["schemas"]["LessonFeedback"];
type FeedbackStatus = Feedback["status"];

function Stars({ rating }: { rating: number | null }) {
  const { t } = useTranslation();
  if (rating === null) return <span className="text-muted-foreground">–</span>;
  return (
    <span aria-label={t("lessonFeedback.starsLabel", { count: rating })}>
      <span aria-hidden="true">{"★".repeat(rating) + "☆".repeat(5 - rating)}</span>
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
  if (!area.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  return (
    <form
      className="max-w-xl space-y-3"
      aria-label={t("lessonFeedback.settings")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h2 className="font-semibold">{t("lessonFeedback.settings")}</h2>
      {schema.map((d) =>
        d.type === "bool" ? (
          <label key={d.key} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
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
      <p className="text-sm text-muted-foreground">{t("lessonFeedback.consentNote")}</p>
      {canManage ? <Button type="submit">{t("common.save")}</Button> : null}
      {save.isSuccess ? <p role="status">{t("common.saved")}</p> : null}
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </form>
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
  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-semibold">{t("lessonFeedback.title")}</h1>
      {s ? (
        <section aria-label={t("lessonFeedback.summary")} className="grid gap-3 sm:grid-cols-4">
          <div className="rounded-md border border-border p-3">
            <p className="text-sm text-muted-foreground">{t("lessonFeedback.average")}</p>
            <p className="text-2xl font-semibold">{s.average ?? "–"}</p>
          </div>
          <div className="rounded-md border border-border p-3">
            <p className="text-sm text-muted-foreground">{t("lessonFeedback.answered")}</p>
            <p className="text-2xl font-semibold">
              {t("lessonFeedback.ofAsked", { answered: s.answered, asked: s.asked })}
            </p>
          </div>
          <div className="rounded-md border border-border p-3">
            <p className="text-sm text-muted-foreground">{t("lessonFeedback.answerRate")}</p>
            <p className="text-2xl font-semibold">{s.answer_rate}%</p>
          </div>
          <div className="rounded-md border border-border p-3">
            <p className="text-sm text-muted-foreground">{t("lessonFeedback.low")}</p>
            <p className="text-2xl font-semibold">{(s.stars["1"] ?? 0) + (s.stars["2"] ?? 0)}</p>
          </div>
        </section>
      ) : null}
      {s && s.tutors.length ? (
        <table className="w-full max-w-2xl text-sm">
          <caption className="text-left font-semibold">{t("lessonFeedback.byTutor")}</caption>
          <thead>
            <tr className="text-left">
              <th scope="col">{t("lessonFeedback.tutor")}</th>
              <th scope="col">{t("lessonFeedback.average")}</th>
              <th scope="col">{t("lessonFeedback.answered")}</th>
            </tr>
          </thead>
          <tbody>
            {s.tutors.map((row) => (
              <tr key={row.tutor_id ?? "none"} className="border-t border-border">
                <td>{row.tutor}</td>
                <td>{row.average}</td>
                <td>{t("lessonFeedback.ofAsked", { answered: row.answered, asked: row.asked })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <form
        className="flex flex-wrap gap-3"
        aria-label={t("lessonFeedback.filters")}
        onSubmit={(e) => e.preventDefault()}
      >
        <SelectField
          label={t("lessonFeedback.status")}
          value={status}
          onChange={(e) => setStatus(e.target.value as FeedbackStatus | "")}
          options={[
            { value: "", label: t("lessonFeedback.any") },
            ...(["sent", "answered", "expired", "skipped"] as const).map((v) => ({
              value: v,
              label: t(`lessonFeedback.statuses.${v}`),
            })),
          ]}
        />
        <SelectField
          label={t("lessonFeedback.rating")}
          value={rating}
          onChange={(e) => setRating(e.target.value)}
          options={[
            { value: "", label: t("lessonFeedback.any") },
            { value: "low", label: t("lessonFeedback.lowOnly") },
            ...["5", "4", "3", "2", "1"].map((v) => ({
              value: v,
              label: t("lessonFeedback.starsLabel", { count: Number(v) }),
            })),
          ]}
        />
      </form>
      {list.isLoading ? <Spinner className="size-6" label={t("grid.loading")} /> : null}
      {list.data && rows.length === 0 ? <p>{t("lessonFeedback.empty")}</p> : null}
      {rows.length ? (
        <table className="w-full text-sm">
          <caption className="sr-only">{t("lessonFeedback.title")}</caption>
          <thead>
            <tr className="text-left">
              <th scope="col">{t("lessonFeedback.lesson")}</th>
              <th scope="col">{t("lessonFeedback.student")}</th>
              <th scope="col">{t("lessonFeedback.tutor")}</th>
              <th scope="col">{t("lessonFeedback.rating")}</th>
              <th scope="col">{t("lessonFeedback.comment")}</th>
              <th scope="col">{t("lessonFeedback.status")}</th>
              {canManage ? <th scope="col">{t("common.actions")}</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-border align-top">
                <td>
                  {row.lesson_title}
                  <div className="text-muted-foreground">{formatDate(row.lesson_date)}</div>
                </td>
                <td>{row.student.name}</td>
                <td>{row.tutor?.name ?? ""}</td>
                <td>
                  <Stars rating={row.rating} />
                </td>
                <td className="max-w-xs whitespace-pre-wrap">{row.comment}</td>
                <td>
                  {t(`lessonFeedback.statuses.${row.status}`)}
                  {row.skip_reason ? (
                    <div className="text-muted-foreground">
                      {t(`lessonFeedback.skipReasons.${row.skip_reason}`)}
                    </div>
                  ) : null}
                </td>
                {canManage ? (
                  <td>
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
      ) : null}
      {withdraw.error ? <Alert tone="danger">{withdraw.error.message}</Alert> : null}
      {canSeeSettings ? <FeedbackSettings /> : null}
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
  if (!item.data) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
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
      <p className="mb-4 text-sm">
        {f.tutor
          ? t("lessonFeedback.lessonWith", {
              lesson: f.lesson,
              tutor: f.tutor,
              date: formatDate(f.lesson_date),
            })
          : t("lessonFeedback.lessonOn", { lesson: f.lesson, date: formatDate(f.lesson_date) })}
      </p>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (rating) answer.mutate();
        }}
      >
        <fieldset>
          <legend className="text-sm font-medium">{t("lessonFeedback.rateIt")}</legend>
          <div className="mt-2 flex gap-2">
            {[1, 2, 3, 4, 5].map((n) => (
              <label
                key={n}
                className="flex cursor-pointer flex-col items-center rounded-md border border-border px-3 py-2 has-[:checked]:border-brand has-[:checked]:bg-muted has-[:focus-visible]:ring-2"
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
                <span aria-hidden="true" className="text-xl">
                  {n <= rating ? "★" : "☆"}
                </span>
                <span className="text-xs">{t("lessonFeedback.starsLabel", { count: n })}</span>
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
            className="min-h-24 rounded-md border border-border p-2"
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
          <p className="text-sm text-muted-foreground">{t("lessonFeedback.chooseStars")}</p>
        ) : null}
        <Button type="submit" disabled={!rating || answer.isPending}>
          {t("lessonFeedback.send")}
        </Button>
        {answer.error ? <Alert tone="danger">{answer.error.message}</Alert> : null}
      </form>
    </PublicLayout>
  );
}
