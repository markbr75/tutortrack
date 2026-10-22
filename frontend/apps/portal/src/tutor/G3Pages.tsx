import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  figureCell,
  FigureStrip,
  PanelFooter,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { PanelLoading, PortalHeader, TextAreaField } from "../layout/PortalPage";
import { useIsPhone } from "../layout/useIsPhone";

const quiet = "text-muted-foreground hover:text-foreground";

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
    <RuledPanel
      title={t("g3.annual.title")}
      description={
        summary.data
          ? t(summary.data.basis === "tax_year" ? "g3.annual.taxYear" : "g3.annual.calendar", {
              start: formatDate(summary.data.start, i18n.language),
              end: formatDate(summary.data.end, i18n.language),
            })
          : undefined
      }
      aside={
        <SelectField
          size="sm"
          hideLabel
          label={t("g3.annual.year")}
          className="tabular-nums"
          value={String(year)}
          onChange={(e) => setYear(Number(e.target.value))}
          options={[thisYear, thisYear - 1, thisYear - 2].map((y) => ({
            value: String(y),
            label: String(y),
          }))}
        />
      }
      flush
      footer={
        <a
          className={buttonClass({ variant: "secondary", size: "sm" })}
          href={`/api/v1/me/earnings/annual?year=${year}&pdf=true`}
        >
          {t("g3.annual.pdf")}
        </a>
      }
    >
      {summary.data ? (
        summary.data.currencies.length ? (
          <div className="px-5">
            {summary.data.currencies.map((c) => (
              <FigureStrip
                key={c.currency}
                className="border-y-0"
                label={t("g3.annual.title")}
                figures={[
                  {
                    key: "earnings",
                    label: t("g3.annual.earnings"),
                    value: formatMoney(c.earnings, i18n.language),
                  },
                  {
                    key: "expenses",
                    label: t("g3.annual.expenses"),
                    value: formatMoney(c.reimbursements, i18n.language),
                  },
                  {
                    key: "total",
                    label: t("g3.annual.total"),
                    value: formatMoney(c.total, i18n.language),
                  },
                ]}
              />
            ))}
          </div>
        ) : (
          <p className="px-5 py-4 text-sm text-muted-foreground">{t("g3.annual.nothing")}</p>
        )
      ) : (
        <PanelLoading label={t("grid.loading")} />
      )}
    </RuledPanel>
  );
}

/** Check your lessons before invoices go out (FR-10-3, gap G3): dates, students and
 * lessons only; confirm, or say what's wrong (those invoices are held for the office). */
export function InvoiceReviewPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const phone = useIsPhone();
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
  if (!reviews.data) return <Spinner label={t("grid.loading")} />;
  const rows = reviews.data.results;
  const date = (iso: string) => formatDate(iso, i18n.language);
  return (
    <div>
      <PortalHeader title={t("g3.tutorReview.pageTitle")} description={t("g3.tutorReview.help")} />
      {!rows.length ? (
        <p className="text-sm text-muted-foreground">{t("g3.tutorReview.nothing")}</p>
      ) : null}
      <div className="space-y-6">
        {rows.map((review) => {
          const period = t("g3.tutorReview.period", {
            start: date(review.period_start),
            end: date(review.period_end),
          });
          return (
            <article key={review.id} aria-label={period}>
              <RuledPanel
                title={period}
                description={t("g3.tutorReview.until", {
                  when: formatDateTime(review.review_until, i18n.language),
                })}
                rule="margin"
                flush
              >
                <RuledTable
                  caption={t("g3.tutorReview.lessons")}
                  columns={[
                    ...(phone ? [] : [{ key: "date", header: t("g3.tutorReview.date") }]),
                    { key: "lesson", header: t("g3.tutorReview.lesson") },
                    ...(phone ? [] : [{ key: "student", header: t("g3.tutorReview.student") }]),
                    {
                      key: "minutes",
                      header: t("g3.tutorReview.minutes"),
                      end: true,
                      width: "w-24",
                    },
                  ]}
                >
                  {review.lessons.map((l, i) => (
                    <tr key={`${l.lesson_id ?? i}`}>
                      {phone ? null : (
                        <td className="whitespace-nowrap tabular-nums">{date(l.date)}</td>
                      )}
                      <td>
                        {l.description}
                        {phone ? (
                          <span className="block text-xs text-muted-foreground tabular-nums">
                            {date(l.date)} · {l.student}
                          </span>
                        ) : null}
                      </td>
                      {phone ? null : <td>{l.student}</td>}
                      <td className={figureCell}>{l.duration_minutes ?? "–"}</td>
                    </tr>
                  ))}
                </RuledTable>
                {flagging === review.id ? (
                  <form
                    className="border-t border-border"
                    onSubmit={(e) => {
                      e.preventDefault();
                      flag.mutate(review.id);
                    }}
                  >
                    <div className="px-5 py-4">
                      <TextAreaField
                        label={t("g3.tutorReview.whatsWrong")}
                        required
                        maxLength={2000}
                        autoFocus
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                      />
                    </div>
                    <PanelFooter>
                      <Button type="submit" disabled={!comment.trim() || flag.isPending}>
                        {t("g3.tutorReview.send")}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        className={quiet}
                        onClick={() => setFlagging("")}
                      >
                        {t("g3.tutorReview.back")}
                      </Button>
                    </PanelFooter>
                  </form>
                ) : (
                  <PanelFooter>
                    <Button variant="secondary" onClick={() => setFlagging(review.id)}>
                      {t("g3.tutorReview.flag")}
                    </Button>
                    <Button onClick={() => confirm.mutate(review.id)}>
                      {t("g3.tutorReview.confirm")}
                    </Button>
                  </PanelFooter>
                )}
                {confirm.isError || flag.isError ? (
                  <div className="px-5 pb-4">
                    <Alert tone="danger">{(confirm.error ?? flag.error)?.message}</Alert>
                  </div>
                ) : null}
              </RuledPanel>
            </article>
          );
        })}
      </div>
    </div>
  );
}
