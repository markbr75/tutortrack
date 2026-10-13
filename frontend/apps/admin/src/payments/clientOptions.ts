import { unwrap } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

/** Clients as select options (first 200 by name) for split billing and split payments. */
export function useClientOptions() {
  return useQuery({
    queryKey: ["client-options"],
    queryFn: async () => {
      const page = unwrap(
        await api.GET("/api/v1/clients", { params: { query: { page_size: 200 } } }),
      );
      return page.results.map((r) => ({ value: r.id, label: r.display_name }));
    },
  });
}
