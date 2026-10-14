import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, useOrganisation } from "../api";
import { useClientOptions } from "../payments/clientOptions";
import { KeyedSettings } from "./KeyedSettings";

/** What tutors said about their lessons on a run's drafts (FR-10-3, gap G3). */
export function RunTutorReviews({ runId }: { runId: string }) {
  const { t } = useTranslation();
  const reviews = useQuery({
    queryKey: ["invoice-runs", runId, "tutor-reviews"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/invoice-runs/{id}/tutor-reviews", {
          params: { path: { id: runId } },
        }),
      ),
  });
  if (reviews.isPending) return <Spinner className="size-4" label={t("grid.loading")} />;
  return (
    <ul className="mt-2 space-y-1 text-sm">
      {(reviews.data ?? []).map((r) => (
        <li key={r.id}>
          <strong>{r.tutor_name}</strong> · {t(`g3.tutorReview.status.${r.status}`)}
          {r.comment ? <span className="block text-muted-foreground">“{r.comment}”</span> : null}
        </li>
      ))}
    </ul>
  );
}

/** Gap G3 billing options: tutor pre-review, monthly statements and how discounts show. */
export function BillingOptions() {
  const { t } = useTranslation();
  return (
    <div className="space-y-8">
      <section aria-labelledby="g3-billing-review" className="space-y-2">
        <h2 id="g3-billing-review" className="text-lg font-medium">
          {t("g3.billingOptions.review")}
        </h2>
        <KeyedSettings
          area="billing"
          keys={["billing.tutor_review", "billing.tutor_review_days"]}
          label={t("g3.billingOptions.review")}
        />
      </section>
      <section aria-labelledby="g3-billing-statements" className="space-y-2">
        <h2 id="g3-billing-statements" className="text-lg font-medium">
          {t("g3.billingOptions.statements")}
        </h2>
        <KeyedSettings
          area="billing"
          keys={["billing.statement_schedule", "billing.statement_day"]}
          label={t("g3.billingOptions.statements")}
        />
      </section>
      <section aria-labelledby="g3-billing-discounts" className="space-y-2">
        <h2 id="g3-billing-discounts" className="text-lg font-medium">
          {t("g3.billingOptions.discounts")}
        </h2>
        <KeyedSettings
          area="pricing"
          keys={["pricing.discount_display"]}
          label={t("g3.billingOptions.discounts")}
        />
      </section>
    </div>
  );
}

const MANUAL = ["bank_transfer", "cash", "cheque", "other"] as const;
type Row = { client: string; amount: string; method: string; reference: string; date: string };
const EMPTY: Row = { client: "", amount: "", method: "bank_transfer", reference: "", date: "" };

/** The bulk payment-entry grid (FR-11-5, gap G3): several manual payments at once, each
 * paying that client's oldest invoices first. All rows are recorded, or none. */
export function BulkPayments() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: org } = useOrganisation();
  const clients = useClientOptions();
  const [rows, setRows] = useState<Row[]>([{ ...EMPTY }, { ...EMPTY }, { ...EMPTY }]);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const currency = org?.default_currency ?? "GBP";
  const filled = rows.filter((r) => r.client && r.amount);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/payments/bulk", {
          params: { header: { "Idempotency-Key": key } },
          body: {
            rows: filled.map((r) => ({
              client: r.client,
              amount: { amount: r.amount, currency },
              method: r.method as (typeof MANUAL)[number],
              reference: r.reference,
              received_at: r.date ? new Date(`${r.date}T12:00:00`).toISOString() : null,
            })),
          },
        }),
      ),
    onSuccess: () => {
      setRows([{ ...EMPTY }, { ...EMPTY }, { ...EMPTY }]);
      setKey(crypto.randomUUID());
      void queryClient.invalidateQueries({ queryKey: ["payments"] });
      void queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
  });
  const rowErrors = ((save.error as { problem?: { errors?: { rows?: Record<string, unknown> } } })
    ?.problem?.errors?.rows ?? {}) as Record<string, unknown>;
  const update = (i: number, change: Partial<Row>) =>
    setRows((all) => all.map((r, n) => (n === i ? { ...r, ...change } : r)));
  return (
    <form
      className="space-y-3"
      aria-label={t("g3.bulkPayments.title")}
      onSubmit={(e) => {
        e.preventDefault();
        if (filled.length) save.mutate();
      }}
    >
      <p className="text-sm text-muted-foreground">{t("g3.bulkPayments.help")}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("g3.bulkPayments.title")}</caption>
          <thead>
            <tr className="text-left">
              {["client", "amount", "method", "date", "reference"].map((h) => (
                <th key={h} scope="col" className="px-1 py-1">
                  {t(`g3.bulkPayments.${h}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="align-top">
                <td className="px-1 py-1">
                  <SelectField
                    label={t("g3.bulkPayments.rowClient", { n: i + 1 })}
                    className="min-w-48"
                    value={row.client}
                    onChange={(e) => update(i, { client: e.target.value })}
                    options={[
                      { value: "", label: t("g3.bulkPayments.chooseClient") },
                      ...(clients.data ?? []),
                    ]}
                  />
                </td>
                <td className="px-1 py-1">
                  <TextField
                    label={t("g3.bulkPayments.rowAmount", { n: i + 1 })}
                    type="number"
                    min={0}
                    step="0.01"
                    className="w-28"
                    value={row.amount}
                    onChange={(e) => update(i, { amount: e.target.value })}
                  />
                </td>
                <td className="px-1 py-1">
                  <SelectField
                    label={t("g3.bulkPayments.rowMethod", { n: i + 1 })}
                    value={row.method}
                    onChange={(e) => update(i, { method: e.target.value })}
                    options={MANUAL.map((m) => ({
                      value: m,
                      label: t(`g3.bulkPayments.methods.${m}`),
                    }))}
                  />
                </td>
                <td className="px-1 py-1">
                  <TextField
                    label={t("g3.bulkPayments.rowDate", { n: i + 1 })}
                    type="date"
                    value={row.date}
                    onChange={(e) => update(i, { date: e.target.value })}
                  />
                </td>
                <td className="px-1 py-1">
                  <TextField
                    label={t("g3.bulkPayments.rowReference", { n: i + 1 })}
                    value={row.reference}
                    maxLength={120}
                    onChange={(e) => update(i, { reference: e.target.value })}
                  />
                  {rowErrors[String(filled.indexOf(row))] ? (
                    <p role="alert" className="text-xs text-danger">
                      {t("g3.bulkPayments.rowFailed")}
                    </p>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="secondary"
          onClick={() => setRows((r) => [...r, { ...EMPTY }])}
        >
          {t("g3.bulkPayments.addRow")}
        </Button>
        <Button type="submit" disabled={save.isPending || !filled.length}>
          {t("g3.bulkPayments.record", { count: filled.length })}
        </Button>
      </div>
      {save.isError ? <Alert tone="danger">{save.error.message}</Alert> : null}
      {save.isSuccess ? (
        <p role="status">{t("g3.bulkPayments.done", { count: save.data.length })}</p>
      ) : null}
    </form>
  );
}
