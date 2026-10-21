import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, RuledPanel, SelectField } from "@tutortrack/ui";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { ledgerLabel, useBranches } from "./ledgers";
import { providerName } from "./providerName";

type Connection = components["schemas"]["AccountingConnection"];

const PROVIDERS = ["xero", "quickbooks", "sage", "freeagent"] as const;
const RETURN_PATH = "/settings/accounting";

/** Gap G5 (FR-23-1): pick which ledger the page shows when there is more than one (the
 * organisation's and branches' own). */
export function LedgerPicker({
  connections,
  value,
  onChange,
}: {
  connections: Connection[];
  value: string;
  onChange: (id: string) => void;
}) {
  const { t } = useTranslation();
  if (connections.length < 2) return null;
  return (
    <div className="max-w-md">
      <SelectField
        label={t("accountingG5.ledger")}
        hint={t("accountingG5.ledgerHelp")}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        options={connections.map((c) => ({ value: c.id, label: ledgerLabel(t, c) }))}
      />
    </div>
  );
}

/** Gap G5 (FR-23-1): connect a separate ledger (its own Xero organisation, QuickBooks
 * company...) for one branch. Its records then go there instead of to the organisation's. */
export function BranchLedgers({ connections }: { connections: Connection[] }) {
  const { t } = useTranslation();
  const branches = useBranches();
  const [branch, setBranch] = useState("");
  const start = useMutation({
    mutationFn: async (provider: string) =>
      unwrap(
        await api.POST("/api/v1/integrations/oauth/start", {
          body: { provider, level: "branch", branch, next: RETURN_PATH },
        }),
      ),
    onSuccess: (result) => window.location.assign(result.authorize_url),
  });
  const rows = branches.data ?? [];
  if (rows.length < 2) return null;
  const taken = new Set(connections.filter((c) => c.branch && c.enabled).map((c) => c.branch));
  const own = connections.filter((c) => c.branch);
  return (
    <RuledPanel
      flush
      titleId="branch-ledgers-heading"
      title={t("accountingG5.branchLedgers")}
      description={t("accountingG5.branchLedgersHelp")}
      footer={
        branch
          ? PROVIDERS.map((p) => (
              <Button key={p} variant="secondary" onClick={() => start.mutate(p)}>
                {t("accountingG5.connectFor", { provider: providerName(t, p) })}
              </Button>
            ))
          : undefined
      }
    >
      {own.length ? (
        <ul className="text-sm">
          {own.map((c) => (
            <li
              key={c.id}
              className="flex flex-wrap justify-between gap-x-4 border-b border-rule px-5 py-2.5"
            >
              <span className="font-medium">{ledgerLabel(t, c)}</span>
              <span className="text-muted-foreground">
                {c.enabled ? t("accountingG5.syncing") : t("accountingG5.notSyncing")}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="max-w-md space-y-3 px-5 py-4">
        <SelectField
          label={t("accountingG5.branch")}
          value={branch}
          onChange={(e) => setBranch(e.target.value)}
          options={[
            { value: "", label: t("accountingG5.chooseBranch") },
            ...rows.map((b) => ({
              value: b.id,
              label: taken.has(b.id) ? t("accountingG5.hasLedger", { branch: b.name }) : b.name,
            })),
          ]}
        />
        <ErrorList error={start.error} />
      </div>
    </RuledPanel>
  );
}
