import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, usePermission } from "../api";
import { ErrorList } from "./ErrorList";

export type VideoAttendance = components["schemas"]["VideoAttendance"];
type Recording = components["schemas"]["LessonRecording"];

/** The register suggested by who joined the online lesson (E22-T10). */
export function VideoAttendanceHint({
  lessonId,
  onApply,
}: {
  lessonId: string;
  onApply: (suggestion: VideoAttendance) => void;
}) {
  const { t } = useTranslation();
  const data = useQuery({
    queryKey: ["video-attendance", lessonId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/lessons/{id}/video-attendance", {
          params: { path: { id: lessonId } },
        }),
      ),
  });
  if (!data.data?.available) return null;
  const s = data.data;
  return (
    <div className="rounded-md border border-border p-3 text-sm" role="note">
      <p className="font-medium">{t("videoLessons.fromVideo")}</p>
      <ul className="my-1 list-disc pl-5">
        {s.students.map((row) => (
          <li key={row.attendee_id}>
            {t(`videoLessons.suggestion.${row.suggested_outcome}`, {
              name: row.name,
              minutes: row.late_minutes ?? 0,
            })}
          </li>
        ))}
      </ul>
      {s.actual_minutes !== null ? (
        <p>{t("videoLessons.actualMinutes", { count: s.actual_minutes })}</p>
      ) : null}
      <Button size="sm" variant="secondary" type="button" onClick={() => onApply(s)}>
        {t("videoLessons.useSuggestion")}
      </Button>
    </div>
  );
}

/** Recordings of a lesson for staff and the lesson's tutor (E22-T10). Opening one is
 * access-checked and audited on the server. */
export function LessonRecordings({ lessonId }: { lessonId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canView = usePermission("video.recording.view");
  const canManage = usePermission("video.recording.manage");
  const recordings = useQuery({
    queryKey: ["recordings", lessonId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/recordings", { params: { query: { lesson: lessonId } } })),
    enabled: canView || canManage,
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["recordings", lessonId] });
  const play = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.GET("/api/v1/recordings/{id}/play", { params: { path: { id } } })),
    onSuccess: (link) => window.open(link.url, "_blank", "noopener"),
  });
  const update = useMutation({
    mutationFn: async ({
      id,
      body,
    }: {
      id: string;
      body: { release?: boolean; share_with_family?: boolean };
    }) => unwrap(await api.PATCH("/api/v1/recordings/{id}", { params: { path: { id } }, body })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      api.DELETE("/api/v1/recordings/{id}", { params: { path: { id } } }),
    onSuccess: refresh,
  });
  const rows: Recording[] = (recordings.data?.results ?? []).filter((r) => r.status !== "deleted");
  if (!rows.length) return null;
  return (
    <section className="mt-3 space-y-2 text-sm" aria-labelledby={`recordings-${lessonId}`}>
      <h3 id={`recordings-${lessonId}`} className="font-medium">
        {t("videoLessons.recordings")}
      </h3>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.id} className="rounded-md border border-border p-2">
            <p>
              {r.started_at
                ? formatDateTime(r.started_at, i18n.language)
                : t("videoLessons.recording")}
              {" · "}
              {t("videoLessons.minutes", { count: Math.round(r.duration_seconds / 60) })}
              {" · "}
              {t(`videoLessons.recordingStatus.${r.status}`)}
              {r.shared_with_family ? ` · ${t("videoLessons.sharedWithFamily")}` : ""}
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {r.status === "available" || canManage ? (
                <Button size="sm" variant="secondary" onClick={() => play.mutate(r.id)}>
                  {t("videoLessons.watch")}
                </Button>
              ) : null}
              {canManage && r.status === "restricted" ? (
                <Button
                  size="sm"
                  onClick={() => update.mutate({ id: r.id, body: { release: true } })}
                >
                  {t("videoLessons.release")}
                </Button>
              ) : null}
              {canManage && r.status === "available" ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    update.mutate({ id: r.id, body: { share_with_family: !r.shared_with_family } })
                  }
                >
                  {r.shared_with_family ? t("videoLessons.unshare") : t("videoLessons.share")}
                </Button>
              ) : null}
              {canManage ? (
                <Button size="sm" variant="ghost" onClick={() => remove.mutate(r.id)}>
                  {t("videoLessons.delete")}
                </Button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      <ErrorList error={play.error ?? update.error ?? remove.error} />
    </section>
  );
}
