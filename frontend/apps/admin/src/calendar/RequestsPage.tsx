import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, ErrorFallback, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "./ErrorList";

type ChangeRequest = components["schemas"]["LessonChangeRequest"];
type Booking = components["schemas"]["BookingHold"];
type TimeOff = components["schemas"]["Exception"];

/** Requests waiting for staff (E08-T13..T15): lesson moves, online bookings needing
 * approval and tutors' time off. Undecided items are declined automatically by their
 * workflows. */
export function RequestsPage() {
  const { t } = useTranslation();
  const canEdit = usePermission("scheduling.lesson.edit");
  const canBook = usePermission("scheduling.lesson.create");
  const canTimeOff = usePermission("scheduling.availability.manage_others");
  return (
    <section className="space-y-8">
      <h1 className="text-2xl font-semibold">{t("requests.title")}</h1>
      {canEdit ? <RescheduleList /> : null}
      {canBook ? <BookingList /> : null}
      {canTimeOff ? <TimeOffList /> : null}
    </section>
  );
}

function Block({
  title,
  query,
  empty,
  children,
}: {
  title: string;
  query: { isPending: boolean; isError: boolean; refetch: () => unknown };
  empty: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section className="space-y-3" aria-label={title}>
      <h2 className="text-lg font-semibold">{title}</h2>
      {query.isError ? (
        <ErrorFallback
          title={t("errors.generic")}
          retryLabel={t("errors.retry")}
          onRetry={() => void query.refetch()}
        />
      ) : query.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : empty ? (
        <p className="text-sm text-muted-foreground">{t("requests.none")}</p>
      ) : (
        <ul className="space-y-3">{children}</ul>
      )}
    </section>
  );
}

function when(value: string, locale: string): string {
  return new Date(value).toLocaleString(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function RescheduleList() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const requests = useQuery({
    queryKey: ["requests", "reschedule"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reschedule-requests", {
          params: { query: { status: "pending" } },
        }),
      ),
  });
  const decide = useMutation({
    mutationFn: async ({
      item,
      approve,
      choice,
    }: {
      item: ChangeRequest;
      approve: boolean;
      choice: number;
    }) =>
      unwrap(
        await api.POST("/api/v1/reschedule-requests/{id}/decide", {
          params: { path: { id: item.id } },
          body: { approve, choice, note: "", override_conflicts: false },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
      void queryClient.invalidateQueries({ queryKey: ["calendar"] });
    },
  });
  const rows = requests.data?.results ?? [];
  return (
    <Block title={t("requests.reschedule")} query={requests} empty={!rows.length}>
      {rows.map((item) => (
        <li key={item.id} className="rounded-lg border border-border p-3">
          <p className="font-medium">{item.lesson_title}</p>
          <p className="text-sm">
            {t("requests.from", { when: when(item.original_start, i18n.language) })} ·{" "}
            {t(`requests.party.${item.requester}`)}
            {item.reason ? ` · ${item.reason}` : ""}
          </p>
          <p className="text-sm text-muted-foreground">
            {t("requests.deadline", { when: when(item.deadline, i18n.language) })}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {item.proposed.map((option, index) => (
              <Button
                key={option.start}
                size="sm"
                onClick={() => decide.mutate({ item, approve: true, choice: index })}
              >
                {t("requests.moveTo", { when: when(option.start, i18n.language) })}
              </Button>
            ))}
            <Button
              size="sm"
              variant="secondary"
              onClick={() => decide.mutate({ item, approve: false, choice: 0 })}
              aria-label={t("requests.declineNamed", { name: item.lesson_title })}
            >
              {t("requests.decline")}
            </Button>
          </div>
        </li>
      ))}
      <li className="list-none">
        <ErrorList error={decide.error} />
      </li>
    </Block>
  );
}

function BookingList() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const bookings = useQuery({
    queryKey: ["requests", "bookings"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/booking/holds", {
          params: { query: { status: "awaiting_approval" } },
        }),
      ),
  });
  const decide = useMutation({
    mutationFn: async ({ item, approve }: { item: Booking; approve: boolean }) =>
      unwrap(
        await api.POST("/api/v1/booking/holds/{id}/decide", {
          params: { path: { id: item.id } },
          body: { approve, note: "" },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["requests"] }),
  });
  const rows = bookings.data?.results ?? [];
  return (
    <Block title={t("requests.bookings")} query={bookings} empty={!rows.length}>
      {rows.map((item) => (
        <li key={item.id} className="rounded-lg border border-border p-3">
          <p className="font-medium">
            {item.service_name} · {item.student_name}
          </p>
          <p className="text-sm">
            {when(item.start, i18n.language)} · {item.tutor_name}
          </p>
          <div className="mt-2 flex gap-2">
            <Button size="sm" onClick={() => decide.mutate({ item, approve: true })}>
              {t("requests.approve")}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => decide.mutate({ item, approve: false })}
            >
              {t("requests.decline")}
            </Button>
          </div>
        </li>
      ))}
      <li className="list-none">
        <ErrorList error={decide.error} />
      </li>
    </Block>
  );
}

function TimeOffList() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [notes, setNotes] = useState<Record<string, string>>({});
  const timeOff = useQuery({
    queryKey: ["requests", "time-off"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/time-off", { params: { query: { status: "requested" } } })),
  });
  const decide = useMutation({
    mutationFn: async ({ item, approve }: { item: TimeOff; approve: boolean }) =>
      unwrap(
        await api.POST("/api/v1/time-off/{id}/decide", {
          params: { path: { id: item.id } },
          body: { approve, note: notes[item.id] ?? "" },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["requests"] }),
  });
  const rows = timeOff.data?.results ?? [];
  return (
    <Block title={t("requests.timeOff")} query={timeOff} empty={!rows.length}>
      {rows.map((item) => (
        <li key={item.id} className="rounded-lg border border-border p-3">
          <p className="font-medium">{item.tutor_name}</p>
          <p className="text-sm">
            {when(item.start, i18n.language)} – {when(item.end, i18n.language)}
            {item.reason ? ` · ${item.reason}` : ""}
          </p>
          <p className="text-sm text-muted-foreground">{t("requests.coverHint")}</p>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <TextField
              label={t("requests.note")}
              value={notes[item.id] ?? ""}
              onChange={(e) => setNotes({ ...notes, [item.id]: e.target.value })}
            />
            <Button size="sm" onClick={() => decide.mutate({ item, approve: true })}>
              {t("requests.approve")}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => decide.mutate({ item, approve: false })}
            >
              {t("requests.decline")}
            </Button>
          </div>
        </li>
      ))}
      <li className="list-none">
        <ErrorList error={decide.error} />
      </li>
    </Block>
  );
}
