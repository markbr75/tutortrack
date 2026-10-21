import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

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
    // The room opens a few minutes before the start; while it's open, poll faster so a
    // resource shared during the lesson reaches everyone's room (gap G5c, FR-21-8).
    refetchInterval: (query) => (query.state.data?.open ? 15_000 : 60_000),
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
  if (room.isPending) return <Spinner label={t("grid.loading")} />;
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
      <ClassroomResources
        lessonId={lessonId}
        resources={c.resources}
        canShare={c.role === "tutor"}
      />
    </article>
  );
}

type Resource = components["schemas"]["ClassroomResource"];

/** Resources in the room (gap G5c, FR-21-8): anything shared with the lesson, its job or
 * the family's students opens from here; the tutor can put one of their resources into
 * the room during the lesson (everyone's page picks it up within seconds). */
function ClassroomResources({
  lessonId,
  resources,
  canShare,
}: {
  lessonId: string;
  resources: Resource[];
  canShare: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState("");
  const [message, setMessage] = useState("");
  const open = useMutation({
    mutationFn: async (resourceId: string) =>
      unwrap(
        await api.POST("/api/v1/lessons/{id}/classroom/resources/{resource_id}/open", {
          params: { path: { id: lessonId, resource_id: resourceId } },
        }),
      ),
    onSuccess: (link) => window.open(link.url, "_blank", "noopener"),
  });
  const library = useQuery({
    queryKey: ["tutor", "learning", "resources"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/resources", {
          params: { query: { archived: false, page_size: 100 } },
        }),
      ),
    enabled: canShare,
  });
  const share = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/resources/{id}/share", {
          params: { path: { id: chosen } },
          body: { lessons: [lessonId], message },
        }),
      ),
    onSuccess: () => {
      setChosen("");
      setMessage("");
      void queryClient.invalidateQueries({ queryKey: ["classroom", lessonId] });
    },
  });
  const inRoom = new Set(resources.map((r) => r.id));
  const options = (library.data?.results ?? []).filter((r) => !inRoom.has(r.id));
  if (!resources.length && !canShare) return null;
  return (
    <section aria-labelledby="classroom-resources" className="space-y-3 text-sm">
      <h2 id="classroom-resources" className="font-semibold">
        {t("classroom.resources")}
      </h2>
      {resources.length ? (
        <ul className="divide-y divide-rule rounded-xl border border-border bg-surface">
          {resources.map((r) => (
            <li
              key={r.id}
              className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5"
            >
              <span>
                <span className="font-medium">{r.title}</span>
                {r.message ? (
                  <span className="block text-xs text-muted-foreground">{r.message}</span>
                ) : null}
              </span>
              <Button
                size="sm"
                variant="secondary"
                disabled={open.isPending}
                onClick={() => open.mutate(r.id)}
                aria-label={t("g5c.classroom.openResource", { title: r.title })}
              >
                {t("g5c.classroom.open")}
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground">{t("g5c.classroom.none")}</p>
      )}
      {open.error ? <Alert tone="danger">{open.error.message}</Alert> : null}
      {canShare ? (
        <form
          aria-label={t("g5c.classroom.share")}
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (chosen) share.mutate();
          }}
        >
          <SelectField
            label={t("g5c.classroom.choose")}
            value={chosen}
            onChange={(e) => setChosen(e.target.value)}
            options={[
              { value: "", label: t("g5c.classroom.pick") },
              ...options.map((r) => ({ value: r.id, label: r.title })),
            ]}
          />
          <TextField
            label={t("g5c.classroom.message")}
            value={message}
            maxLength={500}
            onChange={(e) => setMessage(e.target.value)}
          />
          <Button type="submit" disabled={!chosen} loading={share.isPending}>
            {t("g5c.classroom.share")}
          </Button>
          {share.error ? <Alert tone="danger">{share.error.message}</Alert> : null}
        </form>
      ) : null}
    </section>
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
  if (recordings.isPending) return <Spinner label={t("grid.loading")} />;
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
