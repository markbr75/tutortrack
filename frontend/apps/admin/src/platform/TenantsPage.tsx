import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Spinner, TextField } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";

const STATUSES = ["", "trial", "active", "past_due", "suspended", "cancelled"] as const;

export function TenantsPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>("");
  const [plan, setPlan] = useState("");
  const tenants = useQuery({
    queryKey: ["platform", "tenants", search, status, plan],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/platform/tenants", {
          params: { query: { search, status, plan, page_size: 100 } },
        }),
      ),
  });
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("platform.tenants")}</h1>
      <div className="flex flex-wrap items-end gap-3">
        <TextField
          label={t("platform.search")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">{t("platform.status")}</span>
          <select
            className="h-10 rounded-md border border-border bg-background px-2"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s ? t(`platform.orgStatus.${s}`) : t("platform.any")}
              </option>
            ))}
          </select>
        </label>
        <TextField
          label={t("platform.plan")}
          value={plan}
          onChange={(e) => setPlan(e.target.value)}
        />
      </div>
      {tenants.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col">{t("platform.organisation")}</th>
              <th scope="col">{t("platform.status")}</th>
              <th scope="col">{t("platform.plan")}</th>
              <th scope="col">{t("platform.mrr")}</th>
              <th scope="col">{t("platform.members")}</th>
              <th scope="col">{t("platform.lastActivity")}</th>
              <th scope="col">{t("platform.created")}</th>
            </tr>
          </thead>
          <tbody>
            {tenants.data?.results.map((row) => (
              <tr key={row.id} className="border-t border-border">
                <td>
                  <Link
                    to="/platform/tenants/$id"
                    params={{ id: row.id }}
                    className="font-medium underline"
                  >
                    {row.name}
                  </Link>{" "}
                  <span className="text-muted-foreground">{row.slug}</span>
                </td>
                <td>{t(`platform.orgStatus.${row.status}`)}</td>
                <td>{row.plan ?? "–"}</td>
                <td>{row.mrr ? formatMoney(row.mrr) : "–"}</td>
                <td>{row.members}</td>
                <td>{row.last_activity ? formatDate(row.last_activity) : "–"}</td>
                <td>{formatDate(row.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
