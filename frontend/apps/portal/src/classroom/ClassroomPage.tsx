import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { JoinButton } from "../JoinButton";
import { PanelEmpty, PortalHeader } from "../layout/PortalPage";

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
    <article aria-labelledby="classroom-title">
      <PortalHeader
        titleId="classroom-title"
        title={c.title}
        description={
          <span className="tabular-nums">
            {formatDateTime(c.start, i18n.language)}
            {c.recording
              ? ` · ${t(c.role === "tutor" ? "classroom.recordingTutor" : "classroom.recordingFamily")}`
              : ""}
          </span>
        }
      />
      <div className="space-y-6">
        <div
          role="note"
          className="rounded-md border border-warning/40 bg-warning/10 px-4 py-3 text-sm"
        >
          <strong className="font-semibold">{t("classroom.safeguarding")}</strong>{" "}
          {c.safeguarding_banner}
        </div>
        {c.consent_needed.length ? (
          <RuledPanel
            label={t("classroom.giveConsent")}
            footer={
              <Button size="sm" onClick={() => consent.mutate()} loading={consent.isPending}>
                {t("classroom.giveConsent")}
              </Button>
            }
          >
            <p className="text-sm">{t("classroom.consentPrompt")}</p>
            {consent.error ? (
              <Alert tone="danger" className="mt-3">
                {consent.error.message}
              </Alert>
            ) : null}
          </RuledPanel>
        ) : null}
        {c.embeddable && c.open ? (
          <div className="aspect-video w-full overflow-hidden rounded-xl border border-border bg-surface">
            <iframe
              title={t("classroom.roomTitle", { title: c.title })}
              src={c.join_url}
              className="size-full"
              allow="camera; microphone; fullscreen; display-capture; autoplay; clipboard-write"
              referrerPolicy="no-referrer"
            />
          </div>
        ) : c.join_url ? (
          <div className="space-y-2">
            <JoinButton
              url={c.join_url}
              start={c.start}
              end={c.end}
              opensAt={c.opens_at ?? c.start}
            />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("classroom.noRoom")}</p>
        )}
        {c.embeddable && !c.open && c.opens_at ? (
          <p className="text-sm text-muted-foreground tabular-nums">
            {t("classroom.opensAt", { when: formatDateTime(c.opens_at, i18n.language) })}
          </p>
        ) : null}
        <ClassroomResources
          lessonId={lessonId}
          resources={c.resources}
          canShare={c.role === "tutor"}
        />
      </div>
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
    <RuledPanel title={t("classroom.resources")} titleId="classroom-resources" flush>
      {resources.length ? (
        <PanelRows>
          {resources.map((r) => (
            <PanelRow key={r.id} className="flex flex-wrap items-center justify-between gap-2">
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
            </PanelRow>
          ))}
        </PanelRows>
      ) : (
        <PanelEmpty>{t("g5c.classroom.none")}</PanelEmpty>
      )}
      {open.error ? (
        <div className="px-5 pb-4">
          <Alert tone="danger">{open.error.message}</Alert>
        </div>
      ) : null}
      {canShare ? (
        <form
          aria-label={t("g5c.classroom.share")}
          className="flex flex-wrap items-end gap-2 border-t border-border px-5 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (chosen) share.mutate();
          }}
        >
          <div className="min-w-44 flex-1">
            <SelectField
              size="sm"
              label={t("g5c.classroom.choose")}
              value={chosen}
              onChange={(e) => setChosen(e.target.value)}
              options={[
                { value: "", label: t("g5c.classroom.pick") },
                ...options.map((r) => ({ value: r.id, label: r.title })),
              ]}
            />
          </div>
          <div className="min-w-44 flex-1">
            <TextField
              size="sm"
              label={t("g5c.classroom.message")}
              value={message}
              maxLength={500}
              onChange={(e) => setMessage(e.target.value)}
            />
          </div>
          <Button
            type="submit"
            size="sm"
            variant="secondary"
            className="h-9"
            disabled={!chosen}
            loading={share.isPending}
          >
            {t("g5c.classroom.share")}
          </Button>
          {share.error ? (
            <Alert tone="danger" className="w-full">
              {share.error.message}
            </Alert>
          ) : null}
        </form>
      ) : null}
    </RuledPanel>
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
    <div>
      <PortalHeader title={t("classroom.recordingsTitle")} />
      <div className="space-y-4">
        <RuledPanel label={t("classroom.recordingsTitle")} flush>
          {rows.length ? (
            <PanelRows>
              {rows.map((r) => (
                <PanelRow key={r.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0">
                    <span className="block font-medium">{r.lesson_title}</span>
                    <span className="block text-xs text-muted-foreground tabular-nums">
                      {formatDateTime(r.lesson_start, i18n.language)}
                    </span>
                  </span>
                  <Button size="sm" variant="secondary" onClick={() => play.mutate(r.id)}>
                    {t("classroom.watch")}
                    <span className="sr-only"> {r.lesson_title}</span>
                  </Button>
                </PanelRow>
              ))}
            </PanelRows>
          ) : (
            <PanelEmpty>{t("classroom.noRecordings")}</PanelEmpty>
          )}
        </RuledPanel>
        {play.error ? <Alert tone="danger">{play.error.message}</Alert> : null}
      </div>
    </div>
  );
}
