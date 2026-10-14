import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api } from "../api";
import { JoinButton } from "../JoinButton";

/** The in-app classroom (E22-T10, FR-22-5): the built-in or Lessonspace room embedded for
 * the lesson's tutor and family, the safeguarding banner, the recording consent prompt and
 * the lesson's shared resources. Zoom, Teams and Meet open in their own app. */
export function ClassroomPage({ lessonId }: { lessonId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const room = useQuery({
    queryKey: ["classroom", lessonId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/lessons/{id}/classroom", { params: { path: { id: lessonId } } }),
      ),
    refetchInterval: 60_000, // the room opens a few minutes before the start
  });
  const consent = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/lessons/{id}/classroom/consent", {
          params: { path: { id: lessonId } },
          body: {},
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["classroom", lessonId] }),
  });
  if (room.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  if (!room.data) return <Alert tone="danger">{t("classroom.unavailable")}</Alert>;
  const c = room.data;
  return (
    <article className="space-y-4" aria-labelledby="classroom-title">
      <header>
        <h1 id="classroom-title" className="text-xl font-semibold">
          {c.title}
        </h1>
        <p className="text-sm text-muted-foreground">{formatDateTime(c.start, i18n.language)}</p>
      </header>
      <div
        role="note"
        className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"
      >
        <strong>{t("classroom.safeguarding")}</strong> {c.safeguarding_banner}
      </div>
      {c.recording ? (
        <p className="text-sm">
          {t(c.role === "tutor" ? "classroom.recordingTutor" : "classroom.recordingFamily")}
        </p>
      ) : null}
      {c.consent_needed.length ? (
        <div className="space-y-2 rounded-md border border-border p-3 text-sm">
          <p>{t("classroom.consentPrompt")}</p>
          <Button size="sm" onClick={() => consent.mutate()} loading={consent.isPending}>
            {t("classroom.giveConsent")}
          </Button>
          {consent.error ? <Alert tone="danger">{consent.error.message}</Alert> : null}
        </div>
      ) : null}
      {c.embeddable && c.open ? (
        <div className="aspect-video w-full overflow-hidden rounded-lg border border-border">
          <iframe
            title={t("classroom.roomTitle", { title: c.title })}
            src={c.join_url}
            className="size-full"
            allow="camera; microphone; fullscreen; display-capture; autoplay; clipboard-write"
            referrerPolicy="no-referrer"
          />
        </div>
      ) : c.join_url ? (
        <JoinButton url={c.join_url} start={c.start} end={c.end} opensAt={c.opens_at ?? c.start} />
      ) : (
        <p className="text-sm text-muted-foreground">{t("classroom.noRoom")}</p>
      )}
      {c.embeddable && !c.open && c.opens_at ? (
        <p className="text-sm">
          {t("classroom.opensAt", { when: formatDateTime(c.opens_at, i18n.language) })}
        </p>
      ) : null}
      {c.resources.length ? (
        <section aria-labelledby="classroom-resources" className="space-y-1 text-sm">
          <h2 id="classroom-resources" className="font-semibold">
            {t("classroom.resources")}
          </h2>
          <ul className="list-disc pl-5">
            {c.resources.map((r) => (
              <li key={r.id}>
                <Link
                  to={c.role === "tutor" ? "/tutor/resources" : "/learning"}
                  className="underline"
                >
                  {r.title}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}

/** Recordings shared with the family (E22-T10). Links are fetched on demand (audited). */
export function RecordingsPage() {
  const { t, i18n } = useTranslation();
  const recordings = useQuery({
    queryKey: ["family", "recordings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/recordings")),
  });
  const play = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.GET("/api/v1/recordings/{id}/play", { params: { path: { id } } })),
    onSuccess: (link) => window.open(link.url, "_blank", "noopener"),
  });
  if (recordings.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  const rows = recordings.data ?? [];
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("classroom.recordingsTitle")}</h1>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("classroom.noRecordings")}</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li
              key={r.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3 text-sm"
            >
              <span>
                {r.lesson_title} · {formatDateTime(r.lesson_start, i18n.language)}
              </span>
              <Button size="sm" variant="secondary" onClick={() => play.mutate(r.id)}>
                {t("classroom.watch")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {play.error ? <Alert tone="danger">{play.error.message}</Alert> : null}
    </div>
  );
}
