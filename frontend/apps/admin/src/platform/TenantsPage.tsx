import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  cn,
  figureCell,
  PageHeader,
  RuledTable,
  SelectField,
  TextField,
  type RuledColumn,
} from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { useIsPhone } from "../billing/useIsPhone";

const STATUSES = ["", "trial", "active", "past_due", "suspended", "cancelled"] as const;

/** An organisation's status in words: past due waits on the customer and on us (margin red),
 * a closed one needs nothing (faded ink). */
export function orgStatusClass(status: string): string {
  if (status === "past_due") return "font-semibold text-margin";
  if (status === "cancelled") return "text-muted-foreground";
  return "";
}

/** Every organisation, newest first: one compact filter row over a ruled table. */
export function TenantsPage() {
  const { t, i18n } = useTranslation();
  const phone = useIsPhone();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>("");
  const [plan, setPlan] = useState("");
  const [mrrMin, setMrrMin] = useState("");
  const [mrrMax, setMrrMax] = useState("");
  const [sort, setSort] = useState("");
  const tenants = useQuery({
    queryKey: ["platform", "tenants", search, status, plan, mrrMin, mrrMax, sort],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/platform/tenants", {
          params: {
            query: {
              search,
              status,
              plan,
              page_size: 100,
              mrr_min: mrrMin || undefined,
              mrr_max: mrrMax || undefined,
              ordering: sort || undefined,
            },
          },
        }),
      ),
  });
  const rows = tenants.data?.results ?? [];
  const date = (iso: string | null | undefined) => (iso ? formatDate(iso, i18n.language) : "–");
  const columns: RuledColumn[] = phone
    ? [
        { header: t("platform.organisation") },
        { header: t("platform.mrr"), end: true, width: "w-28" },
      ]
    : [
        { header: t("platform.organisation") },
        { header: t("platform.status") },
        { header: t("platform.plan") },
        { header: t("platform.mrr"), end: true, width: "w-32" },
        { header: t("platform.members"), end: true, width: "w-24" },
        { header: t("platform.lastActivity") },
        { header: t("platform.created") },
      ];
  return (
    <div>
      <PageHeader title={t("platform.tenants")} />
      <form
        role="search"
        aria-label={t("designS11.platform.filterOrganisations")}
        className="mb-4 flex flex-wrap items-center gap-2"
        onSubmit={(e) => e.preventDefault()}
      >
        <div className="min-w-56 flex-1">
          <TextField
            label={t("platform.search")}
            hideLabel
            size="sm"
            type="search"
            placeholder={t("designS11.platform.searchOrganisations")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <SelectField
          label={t("platform.status")}
          hideLabel
          size="sm"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={STATUSES.map((s) => ({
            value: s,
            label: s ? t(`platform.orgStatus.${s}`) : t("designS11.platform.anyStatus"),
          }))}
        />
        <div className="w-36">
          <TextField
            label={t("platform.plan")}
            hideLabel
            size="sm"
            placeholder={t("platform.plan")}
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
          />
        </div>
        <div className="w-32">
          <TextField
            label={t("gapG6.mrrMin")}
            hideLabel
            size="sm"
            inputMode="decimal"
            placeholder={t("gapG6.mrrMin")}
            className="tabular-nums"
            value={mrrMin}
            onChange={(e) => setMrrMin(e.target.value)}
          />
        </div>
        <div className="w-32">
          <TextField
            label={t("gapG6.mrrMax")}
            hideLabel
            size="sm"
            inputMode="decimal"
            placeholder={t("gapG6.mrrMax")}
            className="tabular-nums"
            value={mrrMax}
            onChange={(e) => setMrrMax(e.target.value)}
          />
        </div>
        <SelectField
          label={t("gapG6.sort")}
          hideLabel
          size="sm"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          options={[
            { value: "", label: t("gapG6.sortNewest") },
            { value: "-latest_mrr", label: t("gapG6.sortMrr") },
            { value: "name", label: t("gapG6.sortName") },
          ]}
        />
      </form>
      <RuledTable
        framed
        caption={t("platform.tenants")}
        loading={tenants.isPending}
        loadingLabel={t("grid.loading")}
        empty={tenants.data && !rows.length ? t("designS11.platform.noOrganisations") : undefined}
        columns={columns}
      >
        {rows.map((row) => {
          const mrr = row.snapshot_mrr
            ? formatMoney(row.snapshot_mrr, i18n.language)
            : row.mrr
              ? formatMoney(row.mrr, i18n.language)
              : "–";
          const status = (
            <span className={orgStatusClass(row.status)}>
              {t(`platform.orgStatus.${row.status}`)}
            </span>
          );
          return (
            <tr key={row.id}>
              <td className="min-w-48">
                <Link
                  to="/platform/tenants/$id"
                  params={{ id: row.id }}
                  className="font-medium underline-offset-2 hover:underline"
                >
                  {row.name}
                </Link>
                <span className="block text-xs text-muted-foreground tabular-nums">
                  {phone ? (
                    <>
                      {status} · {[row.plan, date(row.created_at)].filter(Boolean).join(" · ")}
                    </>
                  ) : (
                    row.slug
                  )}
                </span>
              </td>
              {phone ? null : (
                <>
                  <td>{status}</td>
                  <td className={cn(!row.plan && "text-muted-foreground")}>{row.plan ?? "–"}</td>
                </>
              )}
              <td className={figureCell}>{mrr}</td>
              {phone ? null : (
                <>
                  <td className={figureCell}>{row.members}</td>
                  <td className="whitespace-nowrap tabular-nums">{date(row.last_activity)}</td>
                  <td className="whitespace-nowrap tabular-nums">{date(row.created_at)}</td>
                </>
              )}
            </tr>
          );
        })}
      </RuledTable>
    </div>
  );
}
