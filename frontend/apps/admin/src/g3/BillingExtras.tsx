import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
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
  if (reviews.isPending) return <Spinner label={t("grid.loading")} />;
  return (
    <ul className="mt-2 text-sm">
      {(reviews.data ?? []).map((r) => (
        <li key={r.id} className="border-t border-rule py-2 first:border-0">
          <span className="font-medium">{r.tutor_name}</span> ·{" "}
          {t(`g3.tutorReview.status.${r.status}`)}
          {r.comment ? (
            <span className="block text-xs text-muted-foreground">“{r.comment}”</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Gap G3 billing options: tutor pre-review and how discounts show. Monthly statements are
 * the "Monthly statements" built-in workflow now (E33 T04). */
export function BillingOptions() {
  const { t } = useTranslation();
  const sections = [
    {
      id: "review",
      area: "billing",
      keys: ["billing.tutor_review", "billing.tutor_review_days"],
    },
    { id: "discounts", area: "pricing", keys: ["pricing.discount_display"] },
  ] as const;
  return (
    <div className="max-w-3xl space-y-6">
      <RuledPanel titleId="g3-billing-statements" title={t("g3.billingOptions.statements")}>
        <p className="px-5 py-4 text-sm">
          {t("g3.billingOptions.statementsMoved")}{" "}
          <Link to="/automations" className="font-medium underline underline-offset-2">
            {t("g3.billingOptions.openWorkflows")}
          </Link>
        </p>
      </RuledPanel>
      {sections.map((section) => (
        <RuledPanel
          key={section.id}
          titleId={`g3-billing-${section.id}`}
          title={t(`g3.billingOptions.${section.id}`)}
        >
          <KeyedSettings
            area={section.area}
            keys={[...section.keys]}
            label={t(`g3.billingOptions.${section.id}`)}
          />
        </RuledPanel>
      ))}
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
    <RuledPanel flush title={t("g3.bulkPayments.title")} description={t("g3.bulkPayments.help")}>
      <form
        aria-label={t("g3.bulkPayments.title")}
        onSubmit={(e) => {
          e.preventDefault();
          if (filled.length) save.mutate();
        }}
      >
        <div
          role="region"
          aria-label={t("g3.bulkPayments.title")}
          tabIndex={0}
          className="relative overflow-x-auto"
        >
          <table className="w-full min-w-[48rem] text-sm">
            <caption className="sr-only">{t("g3.bulkPayments.title")}</caption>
            <thead className="border-b border-border">
              <tr>
                {["client", "amount", "method", "date", "reference"].map((h, n) => (
                  <th
                    key={h}
                    scope="col"
                    className={`py-2.5 pr-2 ${n === 0 ? "pl-5" : "pl-2"} ${h === "amount" ? "text-right" : ""}`}
                  >
                    {t(`g3.bulkPayments.${h}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="align-top">
                  <td className="py-2 pr-2 pl-5">
                    <SelectField
                      label={t("g3.bulkPayments.rowClient", { n: i + 1 })}
                      hideLabel
                      className="min-w-48"
                      value={row.client}
                      onChange={(e) => update(i, { client: e.target.value })}
                      options={[
                        { value: "", label: t("g3.bulkPayments.chooseClient") },
                        ...(clients.data ?? []),
                      ]}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <TextField
                      label={t("g3.bulkPayments.rowAmount", { n: i + 1 })}
                      hideLabel
                      type="number"
                      min={0}
                      step="0.01"
                      inputMode="decimal"
                      className="w-28 text-right tabular-nums"
                      value={row.amount}
                      onChange={(e) => update(i, { amount: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <SelectField
                      label={t("g3.bulkPayments.rowMethod", { n: i + 1 })}
                      hideLabel
                      value={row.method}
                      onChange={(e) => update(i, { method: e.target.value })}
                      options={MANUAL.map((m) => ({
                        value: m,
                        label: t(`g3.bulkPayments.methods.${m}`),
                      }))}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <TextField
                      label={t("g3.bulkPayments.rowDate", { n: i + 1 })}
                      hideLabel
                      type="date"
                      className="tabular-nums"
                      value={row.date}
                      onChange={(e) => update(i, { date: e.target.value })}
                    />
                  </td>
                  <td className="py-2 pr-5 pl-2">
                    <TextField
                      label={t("g3.bulkPayments.rowReference", { n: i + 1 })}
                      hideLabel
                      value={row.reference}
                      maxLength={120}
                      onChange={(e) => update(i, { reference: e.target.value })}
                    />
                    {rowErrors[String(filled.indexOf(row))] ? (
                      <p role="alert" className="mt-1 text-xs text-danger">
                        {t("g3.bulkPayments.rowFailed")}
                      </p>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {save.isError ? (
          <div className="px-5 pb-3">
            <Alert tone="danger">{save.error.message}</Alert>
          </div>
        ) : null}
        <PanelFooter>
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
          {save.isSuccess ? (
            <p role="status" className="text-success">
              {t("g3.bulkPayments.done", { count: save.data.length })}
            </p>
          ) : null}
        </PanelFooter>
      </form>
    </RuledPanel>
  );
}
