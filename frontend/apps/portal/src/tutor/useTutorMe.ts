import { unwrap } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export function useTutorMe() {
  return useQuery({
    queryKey: ["tutor", "me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/me")),
  });
}
