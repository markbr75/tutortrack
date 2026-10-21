import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Panel, PanelRow, PanelRows, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

type Card = components["schemas"]["PublicTutorCard"];

/** A tutor as a family sees them (no contact details). With ``selectable`` the card is a
 * radio option inside the caller's radio group. */
export function TutorCard({
  card,
  selectable = false,
  selected = false,
  name = "tutor",
  onSelect,
}: {
  card: Card;
  selectable?: boolean;
  selected?: boolean;
  name?: string;
  onSelect?: () => void;
}) {
  const { t } = useTranslation();
  const facts = [
    card.rating !== null
      ? t("shortlistShare.rating", { rating: card.rating, count: card.rating_count })
      : "",
    card.years_experience !== null
      ? t("shortlistShare.experience", { count: card.years_experience })
      : "",
    card.online ? t("shortlistShare.online") : "",
    card.in_person ? t("shortlistShare.inPerson") : "",
  ].filter(Boolean);
  const subjects = card.subjects
    .map((s) => (s.level ? `${s.subject} (${s.level})` : s.subject))
    .join(", ");
  const background = [
    card.qualifications.map((q) => q.title).join("; "),
    card.languages.length
      ? t("shortlistShare.languages", { list: card.languages.join(", ") })
      : "",
  ].filter(Boolean);
  const body = (
    <div className="flex gap-3">
      {card.photo_url ? (
        <img src={card.photo_url} alt="" className="size-14 shrink-0 rounded-full object-cover" />
      ) : null}
      <div className="min-w-0 flex-1 text-sm">
        <p className="text-base font-semibold">{card.name}</p>
        {card.headline ? <p className="text-muted-foreground">{card.headline}</p> : null}
        <div className="mt-3 space-y-1 border-t border-rule pt-3">
          {subjects ? <p className="font-medium">{subjects}</p> : null}
          {facts.length ? (
            <p className="text-muted-foreground tabular-nums">{facts.join(" · ")}</p>
          ) : null}
          {background.length ? (
            <p className="text-muted-foreground">{background.join(" · ")}</p>
          ) : null}
          {card.bio ? <p className="pt-1 whitespace-pre-line">{card.bio}</p> : null}
        </div>
      </div>
    </div>
  );
  if (!selectable) {
    return (
      <article
        aria-label={card.name}
        className={
          "rounded-xl border bg-surface p-4 " + (selected ? "border-link" : "border-border")
        }
      >
        {body}
      </article>
    );
  }
  return (
    <label className="block cursor-pointer rounded-xl border border-border bg-surface p-4 hover:bg-muted/60 has-[:checked]:border-link has-[:checked]:bg-muted has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-link">
      <input
        type="radio"
        name={name}
        className="float-right mt-1 ml-3 size-4"
        checked={selected}
        onChange={onSelect}
        aria-label={t("shortlistShare.choose", { name: card.name })}
      />
      {body}
    </label>
  );
}

/** E19-T08: share the job's shortlist with the family and see what they chose. */
export function ShareShortlistSection({ jobId }: { jobId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canShare = usePermission("matching.shortlist.share");
  const [message, setMessage] = useState("");
  const [days, setDays] = useState("14");
  const [chosen, setChosen] = useState<string[]>([]);
  const shortlist = useQuery({
    queryKey: ["shortlist", jobId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/shortlists", { params: { query: { job: jobId } } })),
  });
  const shares = useQuery({
    queryKey: ["shortlist-shares", jobId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/shortlist-shares", { params: { query: { job: jobId } } })),
  });
  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: ["shortlist-shares", jobId] });
  const share = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/shortlist-shares", {
          body: {
            job: jobId,
            message,
            days: Number(days) || null,
            ...(chosen.length ? { tutors: chosen } : {}),
          },
        }),
      ),
    onSuccess: () => {
      setMessage("");
      refresh();
    },
  });
  const revoke = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/shortlist-shares/{id}/revoke", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  const entries = shortlist.data ?? [];
  return (
    <Panel title={t("shortlistShare.title")} flush>
      <p className="px-5 pt-4 text-sm text-muted-foreground">{t("shortlistShare.intro")}</p>
      {canShare ? (
        <form
          className="max-w-xl space-y-4 px-5 py-4"
          aria-label={t("shortlistShare.form")}
          onSubmit={(e) => {
            e.preventDefault();
            share.mutate();
          }}
        >
          {entries.length ? (
            <fieldset>
              <legend className="text-sm font-medium">{t("shortlistShare.which")}</legend>
              {entries.map((entry) => (
                <label key={entry.id} className="mt-1 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={chosen.includes(entry.tutor)}
                    onChange={(e) =>
                      setChosen(
                        e.target.checked
                          ? [...chosen, entry.tutor]
                          : chosen.filter((x) => x !== entry.tutor),
                      )
                    }
                  />
                  {entry.tutor_name}
                </label>
              ))}
              <p className="text-xs text-muted-foreground">{t("shortlistShare.allHint")}</p>
            </fieldset>
          ) : (
            <p className="text-sm text-muted-foreground">{t("shortlistShare.emptyShortlist")}</p>
          )}
          <div className="flex flex-col gap-1">
            <label htmlFor="share-message" className="text-sm font-medium">
              {t("shortlistShare.message")}
            </label>
            <textarea
              id="share-message"
              className="min-h-20 rounded-md border border-field bg-surface px-3 py-2 text-sm"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
          </div>
          <TextField
            label={t("shortlistShare.days")}
            type="number"
            min={1}
            max={90}
            value={days}
            onChange={(e) => setDays(e.target.value)}
          />
          <Button type="submit" disabled={!entries.length || share.isPending}>
            {t("shortlistShare.send")}
          </Button>
          {share.error ? <Alert tone="danger">{share.error.message}</Alert> : null}
        </form>
      ) : null}
      {shares.isLoading ? (
        <div className="px-5 pb-4">
          <Spinner label={t("grid.loading")} />
        </div>
      ) : null}
      {shares.data?.results.length ? (
        <PanelRows className="border-t border-border">
          {shares.data.results.map((s) => (
            <PanelRow key={s.id} className="space-y-0.5">
              <p className="font-medium">
                {t(`shortlistShare.states.${s.state}`)} ·{" "}
                {t("shortlistShare.sentTo", {
                  name: s.contact_name || t("shortlistShare.family"),
                  count: s.tutors.length,
                })}
              </p>
              <p className="text-xs text-muted-foreground">
                {s.viewed_at
                  ? t("shortlistShare.viewed", { date: formatDateTime(s.viewed_at) })
                  : t("shortlistShare.notViewed")}
                {s.state === "active"
                  ? ` · ${t("shortlistShare.until", { date: formatDate(s.expires_at) })}`
                  : ""}
              </p>
              {s.chosen_tutor_name ? (
                <p>
                  {t("shortlistShare.chose", { tutor: s.chosen_tutor_name })}
                  {s.client_note ? ` – “${s.client_note}”` : ""}
                </p>
              ) : null}
              {s.link ? (
                <p className="break-all">
                  <a
                    className="font-medium text-link underline-offset-2 hover:underline"
                    href={s.link}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("shortlistShare.link")}
                  </a>
                </p>
              ) : null}
              {canShare && s.state === "active" ? (
                <Button size="sm" variant="ghost" onClick={() => revoke.mutate(s.id)}>
                  {t("shortlistShare.revoke")}
                </Button>
              ) : null}
            </PanelRow>
          ))}
        </PanelRows>
      ) : null}
    </Panel>
  );
}

/** The family's page behind the shared link (public, minimal personal data). */
export function PublicShortlistPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [tutor, setTutor] = useState("");
  const [note, setNote] = useState("");
  const page = useQuery({
    queryKey: ["public-shortlist", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/shortlists/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const choose = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public/shortlists/{token}", {
          params: { path: { token } },
          body: { tutor, note },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["public-shortlist", token], data),
  });
  if (page.isError) return <PublicLayout title={t("shortlistShare.missing")}>{null}</PublicLayout>;
  if (!page.data) return <Spinner label={t("grid.loading")} />;
  const p = page.data;
  const subject = [p.job.subject, p.job.level].filter(Boolean).join(" ") || p.job.service;
  return (
    <PublicLayout
      title={t("shortlistShare.publicTitle", { subject })}
      subtitle={p.organisation}
      wide
    >
      {p.message ? <p className="mb-4 whitespace-pre-line">{p.message}</p> : null}
      {p.status === "active" ? (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (tutor) choose.mutate();
          }}
        >
          <fieldset className="space-y-3">
            <legend className="mb-1 text-base font-semibold">
              {t("shortlistShare.pick", { students: p.job.students.join(", ") })}
            </legend>
            {p.tutors.map((card) => (
              <TutorCard
                key={card.id}
                card={card}
                selectable
                name="shortlist-tutor"
                selected={tutor === card.id}
                onSelect={() => setTutor(card.id)}
              />
            ))}
          </fieldset>
          <div className="flex flex-col gap-1">
            <label htmlFor="shortlist-note" className="text-sm font-medium">
              {t("shortlistShare.note")}
            </label>
            <textarea
              id="shortlist-note"
              className="min-h-20 rounded-md border border-field bg-surface px-3 py-2"
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <p className="text-sm text-muted-foreground">
            {t("shortlistShare.until", { date: formatDate(p.expires_at) })}
          </p>
          <Button type="submit" disabled={!tutor || choose.isPending}>
            {t("shortlistShare.confirm")}
          </Button>
          {choose.error ? <Alert tone="danger">{choose.error.message}</Alert> : null}
        </form>
      ) : (
        <div role="status" className="space-y-3">
          <p>{t(`shortlistShare.publicStates.${p.status}`)}</p>
          {p.chosen_tutor
            ? p.tutors
                .filter((c) => c.id === p.chosen_tutor)
                .map((card) => <TutorCard key={card.id} card={card} selected />)
            : null}
        </div>
      )}
    </PublicLayout>
  );
}
