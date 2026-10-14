import { unwrap, type components } from "@tutortrack/api-client";
import { formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ReauthPrompt } from "./Reauth";
import { needsReauth } from "./reauthError";

/** Full bank details behind a re-authentication (E12 §6, gap G3). */
export function FullBankDetails({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const canSee = usePermission("payroll.bank_details.view");
  const [asking, setAsking] = useState(false);
  const reveal = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors/{id}/pay-profile", {
          params: { path: { id: tutorId }, query: { full: true } },
        }),
      ),
    onError: (error) => setAsking(needsReauth(error)),
  });
  if (!canSee) return null;
  if (reveal.data) {
    const bank = reveal.data.bank;
    return (
      <dl className="mt-2 grid grid-cols-2 gap-1 text-sm" aria-label={t("g3.payroll.fullBank")}>
        {Object.entries(bank).map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="text-muted-foreground">{key.replace(/_/g, " ")}</dt>
            <dd className="font-mono">{value}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <div className="mt-2">
      {asking ? (
        <ReauthPrompt
          onDone={() => {
            setAsking(false);
            reveal.mutate();
          }}
          onCancel={() => setAsking(false)}
        />
      ) : (
        <Button size="sm" variant="secondary" onClick={() => reveal.mutate()}>
          {t("g3.payroll.showFullBank")}
        </Button>
      )}
      {reveal.isError && !needsReauth(reveal.error) ? (
        <Alert tone="danger">{reveal.error.message}</Alert>
      ) : null}
    </div>
  );
}

/** Links to a tutor's annual earnings summary (FR-12-9) for staff. */
export function AnnualEarningsLinks({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const year = new Date().getFullYear();
  return (
    <p className="mt-2 text-sm">
      {t("g3.payroll.annual")}:{" "}
      {[year, year - 1].map((y) => (
        <a
          key={y}
          className="mr-2 underline"
          href={`/api/v1/tutors/${tutorId}/earnings/annual?year=${y}&pdf=true`}
          target="_blank"
          rel="noreferrer"
        >
          {t("g3.payroll.annualPdf", { year: y })}
        </a>
      ))}
    </p>
  );
}

type PayItem = components["schemas"]["PayItem"];
const MANUAL_KINDS = new Set(["bonus", "referral", "adjustment", "deduction", "salary"]);

function EditItem({ runId, item, onDone }: { runId: string; item: PayItem; onDone: () => void }) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState(item.amount.amount);
  const [description, setDescription] = useState(item.description);
  const [reason, setReason] = useState("");
  const [key] = useState(() => crypto.randomUUID());
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/pay-runs/{id}/edit-item", {
          params: { path: { id: runId }, header: { "Idempotency-Key": key } },
          body: {
            item: item.id,
            amount:
              amount !== item.amount.amount ? { amount, currency: item.amount.currency } : null,
            ...(MANUAL_KINDS.has(item.kind) && description !== item.description
              ? { description }
              : {}),
            reason,
          },
        }),
      ),
    onSuccess: onDone,
  });
  return (
    <form
      className="mt-2 grid gap-2 sm:grid-cols-4 sm:items-end"
      aria-label={t("g3.payroll.editItem", { item: item.description })}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <TextField
        label={t("g3.payroll.newAmount")}
        type="number"
        step="0.01"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
      />
      {MANUAL_KINDS.has(item.kind) ? (
        <TextField
          label={t("g3.payroll.description")}
          value={description}
          maxLength={300}
          onChange={(e) => setDescription(e.target.value)}
        />
      ) : null}
      <TextField
        label={t("g3.payroll.reason")}
        value={reason}
        maxLength={200}
        onChange={(e) => setReason(e.target.value)}
      />
      <Button type="submit" size="sm" disabled={save.isPending}>
        {t("g3.payroll.saveItem")}
      </Button>
      {save.isError ? (
        <Alert tone="danger" className="sm:col-span-4">
          {save.error.message}
        </Alert>
      ) : null}
    </form>
  );
}

/** The run's items, each editable while the run is under review (FR-12-5, gap G3): a new
 * amount becomes a linked correction in the run; the item itself never changes. */
export function RunItems({ runId, editable }: { runId: string; editable: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("payroll.payrun.create");
  const [editing, setEditing] = useState("");
  const items = useQuery({
    queryKey: ["pay-items", "run", runId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/pay-items", {
          params: { query: { pay_run: runId } },
        }),
      ),
  });
  const rows = items.data?.results ?? [];
  const corrections = (id: string) => rows.filter((r) => r.adjusts === id);
  return (
    <section aria-labelledby="run-items" className="space-y-2">
      <h2 id="run-items" className="text-lg font-medium">
        {t("g3.payroll.items")}
      </h2>
      <ul className="divide-y divide-border rounded-md border border-border text-sm">
        {rows
          .filter((r) => !r.adjusts)
          .map((item) => (
            <li key={item.id} className="p-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {item.tutor_name} · {item.description} · {formatMoney(item.amount)}
                  {corrections(item.id).map((c) => (
                    <span key={c.id} className="block text-xs text-muted-foreground">
                      {c.description} ({formatMoney(c.amount)})
                    </span>
                  ))}
                </span>
                {editable && canEdit ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-expanded={editing === item.id}
                    onClick={() => setEditing(editing === item.id ? "" : item.id)}
                  >
                    {t("g3.payroll.edit")}
                    <span className="sr-only"> {item.description}</span>
                  </Button>
                ) : null}
              </div>
              {editing === item.id ? (
                <EditItem
                  runId={runId}
                  item={item}
                  onDone={() => {
                    setEditing("");
                    void queryClient.invalidateQueries({ queryKey: ["pay-items", "run", runId] });
                    void queryClient.invalidateQueries({ queryKey: ["pay-run", runId] });
                  }}
                />
              ) : null}
            </li>
          ))}
      </ul>
    </section>
  );
}
