import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { useTutorMe } from "./useTutorMe";

type Brief = {
  subject?: string;
  level?: string;
  service?: string;
  students?: string[];
  year_groups?: string[];
  mode?: string;
  area?: string;
  schedule?: { weekday: number; time: string; duration_minutes?: number }[];
  start_date?: string | null;
  pay_rate?: { amount: string; currency: string } | null;
  notes?: string;
};
type Offer = components["schemas"]["MyJobOffer"];
type Posting = components["schemas"]["MyPosting"];
type Cover = components["schemas"]["CoverRequest"];

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

function BriefView({ brief }: { brief: Brief }) {
  const { t, i18n } = useTranslation();
  const what = [brief.subject, brief.level].filter(Boolean).join(" ") || brief.service;
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-sm">
      <dt className="text-muted-foreground">{t("tutorJobs.what")}</dt>
      <dd>{what}</dd>
      {brief.students?.length ? (
        <>
          <dt className="text-muted-foreground">{t("tutorJobs.students")}</dt>
          <dd>
            {brief.students.join(", ")}
            {brief.year_groups?.length ? ` (${brief.year_groups.join(", ")})` : ""}
          </dd>
        </>
      ) : null}
      <dt className="text-muted-foreground">{t("tutorJobs.where")}</dt>
      <dd>{brief.mode === "online" ? t("tutorJobs.online") : brief.area || "—"}</dd>
      {brief.schedule?.length ? (
        <>
          <dt className="text-muted-foreground">{t("tutorJobs.when")}</dt>
          <dd>
            {brief.schedule
              .map((s) => `${t(`tutorJobs.days.${WEEKDAYS[s.weekday]}`)} ${s.time}`)
              .join(", ")}
          </dd>
        </>
      ) : null}
      {brief.start_date ? (
        <>
          <dt className="text-muted-foreground">{t("tutorJobs.starts")}</dt>
          <dd>{formatDate(brief.start_date, i18n.language)}</dd>
        </>
      ) : null}
      {brief.pay_rate ? (
        <>
          <dt className="text-muted-foreground">{t("tutorJobs.pay")}</dt>
          <dd>
            {new Intl.NumberFormat(i18n.language, {
              style: "currency",
              currency: brief.pay_rate.currency,
            }).format(Number(brief.pay_rate.amount))}
          </dd>
        </>
      ) : null}
      {brief.notes ? (
        <>
          <dt className="text-muted-foreground">{t("tutorJobs.notes")}</dt>
          <dd>{brief.notes}</dd>
        </>
      ) : null}
    </dl>
  );
}

function OfferCard({ offer }: { offer: Offer }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  const answer = useMutation({
    mutationFn: async (accept: boolean) =>
      unwrap(
        await api.POST("/api/v1/me/job-offers/{id}/{answer}", {
          params: { path: { id: offer.id, answer: accept ? "accept" : "decline" } },
          body: { reason },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["tutor", "job-offers"] }),
  });
  return (
    <li className="space-y-2 rounded-lg border border-border p-3">
      <BriefView brief={offer.brief as Brief} />
      <p className="text-sm font-medium">
        {t(`tutorJobs.offerStatus.${offer.status}`)}
        {offer.status === "sent" && offer.expires_at
          ? ` · ${t("tutorJobs.answerBy", { when: formatDateTime(offer.expires_at, i18n.language) })}`
          : ""}
      </p>
      {offer.status === "sent" ? (
        declining ? (
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              answer.mutate(false);
            }}
          >
            <TextField
              label={t("tutorJobs.declineReason")}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <Button type="submit" variant="secondary" size="sm">
              {t("tutorJobs.decline")}
            </Button>
          </form>
        ) : (
          <div className="flex gap-2">
            <Button size="sm" onClick={() => answer.mutate(true)} disabled={answer.isPending}>
              {t("tutorJobs.accept")}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setDeclining(true)}>
              {t("tutorJobs.decline")}
            </Button>
          </div>
        )
      ) : null}
      {answer.error ? <Alert tone="danger">{answer.error.message}</Alert> : null}
    </li>
  );
}

function PostingCard({ posting }: { posting: Posting }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const apply = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/me/job-postings/{id}/apply", {
          params: { path: { id: posting.id } },
          body: { message },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["tutor", "job-postings"] }),
  });
  return (
    <li className="space-y-2 rounded-lg border border-border p-3">
      <h3 className="font-medium">{posting.title}</h3>
      <BriefView brief={posting.brief as Brief} />
      {posting.applied ? (
        <p className="text-sm font-medium">{t(`tutorJobs.applied.${posting.applied}`)}</p>
      ) : (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            apply.mutate();
          }}
        >
          <TextField
            label={t("tutorJobs.message")}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
          <Button type="submit" size="sm" disabled={apply.isPending}>
            {t("tutorJobs.apply")}
          </Button>
        </form>
      )}
      {apply.error ? <Alert tone="danger">{apply.error.message}</Alert> : null}
    </li>
  );
}

function CoverCard({ cover, tutorId }: { cover: Cover; tutorId: string | undefined }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const accept = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/me/cover-requests/{id}/accept", {
          params: { path: { id: cover.id } },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["tutor", "cover"] }),
  });
  const mine = cover.original_tutor === tutorId;
  return (
    <li className="space-y-1 rounded-lg border border-border p-3 text-sm">
      <ul>
        {cover.lessons.map((l) => (
          <li key={l.id}>
            {l.title} · {formatDateTime(l.start, i18n.language)}
          </li>
        ))}
      </ul>
      <p className="font-medium">
        {mine ? t("tutorJobs.yourRequest") : ""} {t(`tutorJobs.coverStatus.${cover.status}`)}
        {cover.accepted_by_name ? ` · ${cover.accepted_by_name}` : ""}
      </p>
      {!mine && cover.status === "open" ? (
        <Button size="sm" onClick={() => accept.mutate()} disabled={accept.isPending}>
          {t("tutorJobs.takeCover")}
        </Button>
      ) : null}
      {accept.error ? <Alert tone="danger">{accept.error.message}</Alert> : null}
    </li>
  );
}

/** Job offers, the job board and cover requests (E16-T10, E19). */
export function JobsPage() {
  const { t } = useTranslation();
  const offers = useQuery({
    queryKey: ["tutor", "job-offers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/job-offers")),
  });
  const postings = useQuery({
    queryKey: ["tutor", "job-postings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/job-postings")),
  });
  const cover = useQuery({
    queryKey: ["tutor", "cover"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/cover-requests")),
  });
  const me = useTutorMe();
  const tutorId = me.data?.id;
  if (!offers.data || !postings.data || !cover.data) {
    return <Spinner className="size-5" label={t("grid.loading")} />;
  }
  const open = offers.data.filter((o) => o.status === "sent");
  const past = offers.data.filter((o) => o.status !== "sent");
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">{t("tutorJobs.title")}</h1>
      <section aria-labelledby="offers-heading" className="space-y-2">
        <h2 id="offers-heading" className="font-semibold">
          {t("tutorJobs.offers")}
        </h2>
        {open.length === 0 ? <p className="text-sm text-muted-foreground">{t("tutorJobs.noOffers")}</p> : null}
        <ul className="space-y-3">
          {[...open, ...past.slice(0, 5)].map((o) => (
            <OfferCard key={o.id} offer={o} />
          ))}
        </ul>
      </section>
      <section aria-labelledby="board-heading" className="space-y-2">
        <h2 id="board-heading" className="font-semibold">
          {t("tutorJobs.board")}
        </h2>
        {postings.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("tutorJobs.noPostings")}</p>
        ) : null}
        <ul className="space-y-3">
          {postings.data.map((p) => (
            <PostingCard key={p.id} posting={p} />
          ))}
        </ul>
      </section>
      <section aria-labelledby="cover-heading" className="space-y-2">
        <h2 id="cover-heading" className="font-semibold">
          {t("tutorJobs.cover")}
        </h2>
        {cover.data.length === 0 ? <p className="text-sm text-muted-foreground">{t("tutorJobs.noCover")}</p> : null}
        <ul className="space-y-3">
          {cover.data.map((c) => (
            <CoverCard key={c.id} cover={c} tutorId={tutorId} />
          ))}
        </ul>
      </section>
    </div>
  );
}
