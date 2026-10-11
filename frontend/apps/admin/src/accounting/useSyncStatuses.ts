import { unwrap } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api, usePermission } from "../api";
import type { SyncRecord } from "./SyncBadge";

/** Accounting sync status of several records of one type, keyed by record id (E23).
 * Nothing is fetched for people who can't see accounting sync. */
export function useSyncStatuses(objectType: "invoice" | "payment", ids: string[]) {
  const canView = usePermission("integrations.accounting.view");
  const key = [...ids].sort().join(",");
  return useQuery({
    queryKey: ["accounting", "records", objectType, key],
    enabled: canView && ids.length > 0,
    queryFn: async () => {
      const page = unwrap(
        await api.GET("/api/v1/accounting/records", {
          params: { query: { object_type: objectType, object_id: key } },
        }),
      );
      return Object.fromEntries(page.results.map((r) => [r.object_id, r])) as Record<
        string,
        SyncRecord
      >;
    },
  });
}
