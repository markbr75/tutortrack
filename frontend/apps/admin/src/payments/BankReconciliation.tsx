import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Button, PanelFooter, RuledPanel, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { PanelEmpty, PanelLoading, rowClass } from "../billing/moneyUi";
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
    <RuledPanel flush title={t("bank.upload")} description={t("bank.help")}>
      <form
        aria-label={t("bank.upload")}
        onSubmit={(e) => {
          e.preventDefault();
          upload.mutate();
        }}
      >
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3 px-5 py-4">
          <label className="text-sm">
            <span className="mb-1 block font-medium">{t("bank.file")}</span>
            <input
              type="file"
              accept=".csv,.ofx,.qfx,.xml,text/csv"
              className="text-sm text-muted-foreground file:mr-3 file:h-9 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <label className="flex h-9 items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={monthFirst}
              onChange={(e) => setMonthFirst(e.target.checked)}
            />
            {t("bank.monthFirst")}
          </label>
        </div>
        <PanelFooter>
          <Button type="submit" disabled={!file || upload.isPending}>
            {t("bank.import")}
          </Button>
          <Button type="button" size="sm" variant="secondary" onClick={() => sync.mutate()}>
            {t("bank.syncFeed")}
          </Button>
          {upload.data ? (
            <p role="status" className="text-success tabular-nums">
              {t("bank.imported", {
                count: Number((upload.data.stats as Record<string, number>).new ?? 0),
                duplicates: Number((upload.data.stats as Record<string, number>).duplicates ?? 0),
              })}
            </p>
          ) : null}
        </PanelFooter>
        {(upload.error ?? sync.error) ? (
          <div className="px-5 pb-4">
            <ErrorList error={upload.error ?? sync.error} />
          </div>
        ) : null}
      </form>
    </RuledPanel>
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
      className="mt-3 space-y-2 border-t border-rule pt-3"
      aria-label={t("bank.split")}
      onSubmit={(e) => {
        e.preventDefault();
        split.mutate();
      }}
    >
      {parts.map((part, i) => (
        <div key={i} className="grid max-w-xl gap-3 sm:grid-cols-[minmax(0,1fr)_9rem]">
          <SelectField
            label={t("bank.client", { n: i + 1 })}
            value={part.client}
            onChange={(e) => update(i, "client", e.target.value)}
            options={[{ value: "", label: t("bank.chooseClient") }, ...(clients.data ?? [])]}
          />
          <TextField
            label={t("bank.partAmount", { n: i + 1 })}
            className="text-right"
            type="number"
            step="0.01"
            value={part.amount}
            onChange={(e) => update(i, "amount", e.target.value)}
          />
        </div>
      ))}
      <div className="flex flex-wrap gap-2 pt-1">
        <Button type="submit" size="sm">
          {t("bank.recordSplit")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setParts([...parts, { client: "", amount: "" }])}
        >
          {t("bank.addPart")}
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
    <li className={`${rowClass} space-y-2`}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <p className="font-medium">{line.description || line.reference}</p>
          <p className="text-xs text-muted-foreground tabular-nums">
            {formatDate(line.booked_on, i18n.language)}
            {line.counterparty ? ` · ${line.counterparty}` : ""}
          </p>
        </div>
        <div className="text-right">
          <p className="font-semibold tabular-nums">{formatMoney(line.amount, i18n.language)}</p>
          <p className="text-xs text-muted-foreground">{t(`bank.status.${line.status}`)}</p>
        </div>
      </div>
      {open && line.matches.length ? (
        <ul className="space-y-1">
          {line.matches.map((m) => (
            <li
              key={m.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/60 px-3 py-1.5 text-sm"
            >
              <span>
                {m.reason}
                {m.client_name ? ` · ${m.client_name}` : ""} ·{" "}
                <span className="tabular-nums">{t("bank.score", { score: m.score })}</span>
              </span>
              <Button size="sm" onClick={() => act.mutate({ kind: "confirm", match: m.id })}>
                {t("bank.confirm")}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {open || line.status === "ignored" ? (
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
      ) : null}
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
    <div className="space-y-6">
      <Upload onDone={refresh} />
      <div>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <SelectField
            label={t("bank.show")}
            hideLabel
            size="sm"
            value={filter}
            onChange={(e) => setFilter(e.target.value as Filter)}
            options={(["suggested", "unmatched", "matched", "ignored"] as Filter[]).map((f) => ({
              value: f,
              label: t(`bank.status.${f}`),
            }))}
          />
        </div>
        <section
          aria-label={t("bank.title")}
          className="rounded-xl border border-border bg-surface text-sm"
        >
          {list.query.isPending ? (
            <PanelLoading label={t("grid.loading")} />
          ) : list.rows.length ? (
            <ul>
              {list.rows.map((line) => (
                <LineRow key={line.id} line={line} onChange={refresh} />
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("designS7.bank.empty")}</PanelEmpty>
          )}
          {list.query.hasNextPage ? (
            <PanelFooter className="justify-center">
              <Button
                size="sm"
                variant="ghost"
                loading={list.query.isFetchingNextPage}
                onClick={() => void list.query.fetchNextPage()}
              >
                {t("grid.loadMore")}
              </Button>
            </PanelFooter>
          ) : null}
        </section>
      </div>
    </div>
  );
}
