import { unwrap } from "@tutortrack/api-client";

import { api } from "../api";

/** Direct-to-storage image upload (create → PUT → complete); returns the stored file id. */
export async function uploadImage(file: File): Promise<string> {
  const created = unwrap(
    await api.POST("/api/v1/files/uploads", {
      body: {
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        visibility: "internal",
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
