import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";

/** Annual earnings summary for tax returns (FR-12-9, gap G3): what was paid in a year
 * (the UK tax year for UK organisations), by type and month, with a PDF. */
export function AnnualEarnings() {
  const { t, i18n } = useTranslation();
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const summary = useQuery({
    queryKey: ["tutor", "annual-earnings", year],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/me/earnings/annual", { params: { query: { year } } }),
      ) as components["schemas"]["AnnualEarnings"],
  });
  return (
    <section aria-labelledby="annual" className="space-y-2">
      <h2 id="annual" className="font-semibold">
        {t("g3.annual.title")}
      </h2>
      <div className="flex flex-wrap items-end gap-2">
        <SelectField
          label={t("g3.annual.year")}
          value={String(year)}
          onChange={(e) => setYear(Number(e.target.value))}
          options={[thisYear, thisYear - 1, thisYear - 2].map((y) => ({
            value: String(y),
            label: String(y),
          }))}
        />
        <a
          className="rounded-md border border-border px-3 py-1.5 text-sm"
          href={`/api/v1/me/earnings/annual?year=${year}&pdf=true`}
        >
          {t("g3.annual.pdf")}
        </a>
      </div>
      {summary.data ? (
        <>
          <p className="text-sm text-muted-foreground">
            {t(summary.data.basis === "tax_year" ? "g3.annual.taxYear" : "g3.annual.calendar", {
              start: formatDate(summary.data.start, i18n.language),
              end: formatDate(summary.data.end, i18n.language),
            })}
          </p>
          {summary.data.currencies.length ? (
            summary.data.currencies.map((c) => (
              <dl key={c.currency} className="grid grid-cols-3 gap-2 text-sm">
                <div className="rounded-lg border border-border p-3">
                  <dt className="text-muted-foreground">{t("g3.annual.earnings")}</dt>
                  <dd className="font-semibold">{formatMoney(c.earnings, i18n.language)}</dd>
                </div>
                <div className="rounded-lg border border-border p-3">
                  <dt className="text-muted-foreground">{t("g3.annual.expenses")}</dt>
                  <dd className="font-semibold">{formatMoney(c.reimbursements, i18n.language)}</dd>
                </div>
                <div className="rounded-lg border border-border p-3">
                  <dt className="text-muted-foreground">{t("g3.annual.total")}</dt>
                  <dd className="font-semibold">{formatMoney(c.total, i18n.language)}</dd>
                </div>
              </dl>
            ))
          ) : (
            <p className="text-sm">{t("g3.annual.nothing")}</p>
          )}
        </>
      ) : (
        <Spinner className="size-4" label={t("grid.loading")} />
      )}
    </section>
  );
}

/** Check your lessons before invoices go out (FR-10-3, gap G3): dates, students and
 * lessons only; confirm, or say what's wrong (those invoices are held for the office). */
export function InvoiceReviewPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const commentId = useId();
  const [flagging, setFlagging] = useState("");
  const [comment, setComment] = useState("");
  const reviews = useQuery({
    queryKey: ["tutor", "invoice-reviews"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/me/invoice-reviews", { params: { query: { open: true } } })),
  });
  const done = () => {
    setFlagging("");
    setComment("");
    void queryClient.invalidateQueries({ queryKey: ["tutor", "invoice-reviews"] });
  };
  const confirm = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/me/invoice-reviews/{id}/confirm", { params: { path: { id } } }),
      ),
    onSuccess: done,
  });
  const flag = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/me/invoice-reviews/{id}/flag", {
          params: { path: { id } },
          body: { comment },
        }),
      ),
    onSuccess: done,
  });
  if (!reviews.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const rows = reviews.data.results;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("g3.tutorReview.pageTitle")}</h1>
      <p className="text-sm text-muted-foreground">{t("g3.tutorReview.help")}</p>
      {!rows.length ? <p className="text-sm">{t("g3.tutorReview.nothing")}</p> : null}
      {rows.map((review) => (
        <article
          key={review.id}
          className="space-y-2 rounded-lg border border-border p-4"
          aria-label={t("g3.tutorReview.period", {
            start: formatDate(review.period_start, i18n.language),
            end: formatDate(review.period_end, i18n.language),
          })}
        >
          <h2 className="font-semibold">
            {t("g3.tutorReview.period", {
              start: formatDate(review.period_start, i18n.language),
              end: formatDate(review.period_end, i18n.language),
            })}
          </h2>
          <p className="text-xs text-muted-foreground">
            {t("g3.tutorReview.until", {
              when: formatDateTime(review.review_until, i18n.language),
            })}
          </p>
          <table className="w-full text-sm">
            <caption className="sr-only">{t("g3.tutorReview.lessons")}</caption>
            <thead>
              <tr className="text-left">
                <th scope="col">{t("g3.tutorReview.date")}</th>
                <th scope="col">{t("g3.tutorReview.lesson")}</th>
                <th scope="col">{t("g3.tutorReview.student")}</th>
                <th scope="col">{t("g3.tutorReview.minutes")}</th>
              </tr>
            </thead>
            <tbody>
              {review.lessons.map((l, i) => (
                <tr key={`${l.lesson_id ?? i}`} className="border-t border-border">
                  <td>{formatDate(l.date, i18n.language)}</td>
                  <td>{l.description}</td>
                  <td>{l.student}</td>
                  <td>{l.duration_minutes ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {flagging === review.id ? (
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                flag.mutate(review.id);
              }}
            >
              <label htmlFor={commentId} className="text-sm font-medium">
                {t("g3.tutorReview.whatsWrong")}
              </label>
              <textarea
                id={commentId}
                required
                maxLength={2000}
                className="min-h-20 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
              <div className="flex gap-2">
                <Button type="submit" size="sm" disabled={!comment.trim() || flag.isPending}>
                  {t("g3.tutorReview.send")}
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setFlagging("")}>
                  {t("g3.tutorReview.back")}
                </Button>
              </div>
            </form>
          ) : (
            <div className="flex gap-2">
              <Button size="sm" onClick={() => confirm.mutate(review.id)}>
                {t("g3.tutorReview.confirm")}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setFlagging(review.id)}>
                {t("g3.tutorReview.flag")}
              </Button>
            </div>
          )}
          {confirm.isError || flag.isError ? (
            <Alert tone="danger">{(confirm.error ?? flag.error)?.message}</Alert>
          ) : null}
        </article>
      ))}
    </div>
  );
}
