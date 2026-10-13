import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { useCursorList } from "../lists";
import { useClientOptions } from "./clientOptions";

type Line = components["schemas"]["BankTransaction"];
type Filter = "suggested" | "unmatched" | "matched" | "ignored";
type Part = { client: string; amount: string };

/** Upload a CSV, OFX or CAMT.053 statement, or pull the Open Banking feed (E11-T13). */
function Upload({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [monthFirst, setMonthFirst] = useState(false);
  const upload = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      if (file) form.append("file", file);
      form.append("month_first", monthFirst ? "true" : "false");
      return unwrap(
        await api.POST("/api/v1/bank-reconciliation/imports", {
          body: form as never,
          bodySerializer: (body: unknown) => body as FormData,
        }),
      );
    },
    onSuccess: onDone,
  });
  const sync = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/bank-reconciliation/imports/sync")),
    onSuccess: onDone,
  });
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      aria-label={t("bank.upload")}
      onSubmit={(e) => {
        e.preventDefault();
        upload.mutate();
      }}
    >
      <label className="text-sm">
        <span className="block font-medium">{t("bank.file")}</span>
        <input
          type="file"
          accept=".csv,.ofx,.qfx,.xml,text/csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={monthFirst}
          onChange={(e) => setMonthFirst(e.target.checked)}
        />
        {t("bank.monthFirst")}
      </label>
      <Button type="submit" size="sm" disabled={!file || upload.isPending}>
        {t("bank.import")}
      </Button>
      <Button type="button" size="sm" variant="secondary" onClick={() => sync.mutate()}>
        {t("bank.syncFeed")}
      </Button>
      {upload.data ? (
        <Alert tone="success">
          {t("bank.imported", {
            count: Number((upload.data.stats as Record<string, number>).new ?? 0),
            duplicates: Number((upload.data.stats as Record<string, number>).duplicates ?? 0),
          })}
        </Alert>
      ) : null}
      <ErrorList error={upload.error ?? sync.error} />
    </form>
  );
}

function SplitForm({ line, onDone }: { line: Line; onDone: () => void }) {
  const { t } = useTranslation();
  const [parts, setParts] = useState<Part[]>([
    { client: "", amount: "" },
    { client: "", amount: "" },
  ]);
  const clients = useClientOptions();
  const split = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/bank-reconciliation/transactions/{id}/split", {
          params: { path: { id: line.id } },
          body: { payer_name: line.counterparty, parts },
        }),
      ),
    onSuccess: onDone,
  });
  const update = (i: number, key: keyof Part, value: string) =>
    setParts(parts.map((p, j) => (j === i ? { ...p, [key]: value } : p)));
  return (
    <form
      className="mt-2 space-y-2"
      aria-label={t("bank.split")}
      onSubmit={(e) => {
        e.preventDefault();
        split.mutate();
      }}
    >
      {parts.map((part, i) => (
        <div key={i} className="flex flex-wrap gap-2">
          <SelectField
            label={t("bank.client", { n: i + 1 })}
            value={part.client}
            onChange={(e) => update(i, "client", e.target.value)}
            options={[{ value: "", label: t("bank.chooseClient") }, ...(clients.data ?? [])]}
          />
          <TextField
            label={t("bank.partAmount", { n: i + 1 })}
            type="number"
            step="0.01"
            value={part.amount}
            onChange={(e) => update(i, "amount", e.target.value)}
          />
        </div>
      ))}
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setParts([...parts, { client: "", amount: "" }])}
        >
          {t("bank.addPart")}
        </Button>
        <Button type="submit" size="sm">
          {t("bank.recordSplit")}
        </Button>
      </div>
      <ErrorList error={split.error} />
    </form>
  );
}

function LineRow({ line, onChange }: { line: Line; onChange: () => void }) {
  const { t, i18n } = useTranslation();
  const [splitting, setSplitting] = useState(false);
  const act = useMutation({
    mutationFn: async (input: { kind: "confirm" | "ignore" | "reopen"; match?: string }) => {
      const params = { params: { path: { id: line.id } } };
      if (input.kind === "confirm")
        return unwrap(
          await api.POST("/api/v1/bank-reconciliation/transactions/{id}/confirm", {
            ...params,
            body: { match: input.match },
          }),
        );
      if (input.kind === "ignore")
        return unwrap(
          await api.POST("/api/v1/bank-reconciliation/transactions/{id}/ignore", params),
        );
      return unwrap(await api.POST("/api/v1/bank-reconciliation/transactions/{id}/reopen", params));
    },
    onSuccess: onChange,
  });
  const open = line.status === "suggested" || line.status === "unmatched";
  const moneyIn = Number(line.amount.amount) > 0;
  return (
    <li className="space-y-2 p-3">
      <div className="flex flex-wrap justify-between gap-2">
        <span>
          <span className="font-medium">{formatMoney(line.amount, i18n.language)}</span> ·{" "}
          {formatDate(line.booked_on, i18n.language)} · {line.description || line.reference}
        </span>
        <span className="text-muted-foreground">{t(`bank.status.${line.status}`)}</span>
      </div>
      {open && line.matches.length ? (
        <ul className="space-y-1">
          {line.matches.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span>
                {m.reason}
                {m.client_name ? ` · ${m.client_name}` : ""} · {t("bank.score", { score: m.score })}
              </span>
              <Button size="sm" onClick={() => act.mutate({ kind: "confirm", match: m.id })}>
                {t("bank.confirm")}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {open && moneyIn ? (
          <Button size="sm" variant="secondary" onClick={() => setSplitting(!splitting)}>
            {t("bank.split")}
          </Button>
        ) : null}
        {open ? (
          <Button size="sm" variant="ghost" onClick={() => act.mutate({ kind: "ignore" })}>
            {t("bank.ignore")}
          </Button>
        ) : null}
        {line.status === "ignored" ? (
          <Button size="sm" variant="ghost" onClick={() => act.mutate({ kind: "reopen" })}>
            {t("bank.reopen")}
          </Button>
        ) : null}
      </div>
      {splitting ? <SplitForm line={line} onDone={onChange} /> : null}
      <ErrorList error={act.error} />
    </li>
  );
}

/** Billing → Bank: the reconciliation queue (FR-11-5, E11-T13/T14). */
export function BankReconciliation() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<Filter>("suggested");
  const list = useCursorList(["bank-transactions", filter], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/bank-reconciliation/transactions", {
        params: { query: { status: [filter], cursor } },
      }),
    ),
  );
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["bank-transactions"] });
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("bank.help")}</p>
      <Upload onDone={refresh} />
      <SelectField
        label={t("bank.show")}
        value={filter}
        onChange={(e) => setFilter(e.target.value as Filter)}
        options={(["suggested", "unmatched", "matched", "ignored"] as Filter[]).map((f) => ({
          value: f,
          label: t(`bank.status.${f}`),
        }))}
      />
      {list.query.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : list.rows.length ? (
        <ul className="divide-y divide-border rounded-md border border-border text-sm">
          {list.rows.map((line) => (
            <LineRow key={line.id} line={line} onChange={refresh} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{t("grid.empty")}</p>
      )}
    </div>
  );
}
