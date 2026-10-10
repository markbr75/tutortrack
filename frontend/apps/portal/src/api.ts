import { ApiError, createApiClient, unwrap, type components } from "@tutortrack/api-client";
import { QueryClient, useQuery } from "@tanstack/react-query";

export const api = createApiClient();

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      },
    },
  });
}

export type PortalMe = components["schemas"]["PortalMe"];

/** Who the signed-in family member is (household, features, branding). */
export function usePortalMe() {
  return useQuery({
    queryKey: ["portal", "me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/me")),
  });
}

export function problemStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}

/** Direct-to-storage upload (create → PUT → complete); returns the stored file id. */
export async function uploadFile(file: File): Promise<string> {
  const created = unwrap(
    await api.POST("/api/v1/files/uploads", {
      body: {
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        visibility: "private",
      },
    }),
  );
  const put = await fetch(created.upload.url, {
    method: created.upload.method,
    headers: created.upload.headers,
    body: file,
  });
  if (!put.ok) throw new Error("upload failed");
  unwrap(
    await api.POST("/api/v1/files/{id}/complete", { params: { path: { id: created.file.id } } }),
  );
  return created.file.id;
}
