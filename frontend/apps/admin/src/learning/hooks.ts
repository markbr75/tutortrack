import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { MASTERY_LEVELS, type MasteryLevel } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export const PAGE = { page_size: 200 };

export function useStudentOptions() {
  const { t } = useTranslation();
  const students = useQuery({
    queryKey: ["learning", "student-options"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/students", { params: { query: { ...PAGE } } })),
  });
  return [
    { value: "", label: t("learning.chooseStudent") },
    ...(students.data?.results ?? []).map((s) => ({ value: s.id, label: s.full_name })),
  ];
}

/** ``yyyy-mm-ddThh:mm`` from a local datetime input to an ISO string with offset. */
export function localToIso(value: string): string {
  return new Date(value).toISOString();
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

/** Topic names for the lesson report "topics covered" picker (E21-T03). */
export function useTopicSuggestions(enabled: boolean) {
  return useQuery({
    queryKey: ["learning", "topics"],
    enabled,
    staleTime: 300_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/learning/topics")),
  });
}

export function useLevelLabels(): Record<MasteryLevel, string> {
  const { t } = useTranslation();
  return Object.fromEntries(
    MASTERY_LEVELS.map((level) => [level, t(`learning.levels.${level}`)]),
  ) as Record<MasteryLevel, string>;
}
