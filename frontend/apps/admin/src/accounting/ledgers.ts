import { unwrap, type components } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { providerName } from "./providerName";

type Connection = components["schemas"]["AccountingConnection"];

export function useBranches() {
  return useQuery({
    queryKey: ["branches", "accounting"],
    queryFn: async () => unwrap(await api.GET("/api/v1/branches")).results,
  });
}

/** How a ledger is named on the page: its provider and whose books it keeps. */
export function ledgerLabel(
  t: (key: string, o?: Record<string, unknown>) => string,
  conn: Connection,
) {
  const provider = providerName(t, conn.provider);
  return conn.branch
    ? t("accountingG5.forBranch", { provider, branch: conn.branch_name ?? "" })
    : t("accountingG5.wholeOrganisation", { provider });
}
