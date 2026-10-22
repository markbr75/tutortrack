import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, FactList, RuledPanel, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api } from "../api";
import { PanelEmpty, PortalHeader, Word } from "../layout/PortalPage";
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

/** A job's brief as ruled facts (what, students, where, when, start, pay, notes). */
function BriefView({ brief }: { brief: Brief }) {
  const { t, i18n } = useTranslation();
  const what = [brief.subject, brief.level].filter(Boolean).join(" ") || brief.service;
  return (
    <FactList
      className="border-y border-rule"
      items={[
        [t("tutorJobs.what"), what],
        [
          t("tutorJobs.students"),
          brief.students?.length
            ? `${brief.students.join(", ")}${brief.year_groups?.length ? ` (${brief.year_groups.join(", ")})` : ""}`
            : "",
        ],
        [t("tutorJobs.where"), brief.mode === "online" ? t("tutorJobs.online") : brief.area || "–"],
        [
          t("tutorJobs.when"),
          brief.schedule?.length
            ? brief.schedule
                .map((s) => `${t(`tutorJobs.days.${WEEKDAYS[s.weekday]}`)} ${s.time}`)
                .join(", ")
            : "",
        ],
        [
          t("tutorJobs.starts"),
          brief.start_date ? formatDate(brief.start_date, i18n.language) : "",
        ],
        [
          t("tutorJobs.pay"),
          brief.pay_rate ? (
            <span className="tabular-nums">
              {new Intl.NumberFormat(i18n.language, {
                style: "currency",
                currency: brief.pay_rate.currency,
              }).format(Number(brief.pay_rate.amount))}
            </span>
          ) : (
            ""
          ),
        ],
        [t("tutorJobs.notes"), brief.notes ?? ""],
      ]}
    />
  );
}

/** One job (offer, posting or cover) inside a panel: a heading line, the brief, actions. */
function JobRow({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <li className="py-3.5">
      <div className="px-5 pb-2">{head}</div>
      {children}
    </li>
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
  const open = offer.status === "sent";
  return (
    <JobRow
      head={
        <p className="text-sm">
          <Word tone={open ? "ink" : "muted"} className={open ? "font-medium" : ""}>
            {t(`tutorJobs.offerStatus.${offer.status}`)}
          </Word>
          {open && offer.expires_at ? (
            <span className="text-muted-foreground tabular-nums">
              {" "}
              · {t("tutorJobs.answerBy", { when: formatDateTime(offer.expires_at, i18n.language) })}
            </span>
          ) : null}
        </p>
      }
    >
      <BriefView brief={offer.brief as Brief} />
      {open ? (
        declining ? (
          <form
            className="flex flex-wrap items-end gap-2 px-5 pt-3"
            onSubmit={(e) => {
              e.preventDefault();
              answer.mutate(false);
            }}
          >
            <div className="min-w-48 flex-1">
              <TextField
                size="sm"
                label={t("tutorJobs.declineReason")}
                autoFocus
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
            <Button type="submit" variant="secondary" size="sm" className="h-9">
              {t("tutorJobs.decline")}
            </Button>
          </form>
        ) : (
          <div className="flex flex-wrap gap-2 px-5 pt-3">
            <Button size="sm" variant="secondary" onClick={() => setDeclining(true)}>
              {t("tutorJobs.decline")}
            </Button>
            <Button size="sm" onClick={() => answer.mutate(true)} disabled={answer.isPending}>
              {t("tutorJobs.accept")}
            </Button>
          </div>
        )
      ) : null}
      {answer.error ? (
        <div className="px-5 pt-3">
          <Alert tone="danger">{answer.error.message}</Alert>
        </div>
      ) : null}
    </JobRow>
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
    <JobRow head={<h3 className="font-medium">{posting.title}</h3>}>
      <BriefView brief={posting.brief as Brief} />
      {posting.applied ? (
        <p className="px-5 pt-3 text-sm font-medium">{t(`tutorJobs.applied.${posting.applied}`)}</p>
      ) : (
        <form
          className="flex flex-wrap items-end gap-2 px-5 pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            apply.mutate();
          }}
        >
          <div className="min-w-48 flex-1">
            <TextField
              size="sm"
              label={t("tutorJobs.message")}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
          </div>
          <Button type="submit" size="sm" className="h-9" disabled={apply.isPending}>
            {t("tutorJobs.apply")}
          </Button>
        </form>
      )}
      {apply.error ? (
        <div className="px-5 pt-3">
          <Alert tone="danger">{apply.error.message}</Alert>
        </div>
      ) : null}
    </JobRow>
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
    <li className="space-y-2 px-5 py-3 text-sm">
      <ul className="space-y-0.5">
        {cover.lessons.map((l) => (
          <li key={l.id}>
            <span className="font-medium">{l.title}</span>{" "}
            <span className="text-muted-foreground tabular-nums">
              · {formatDateTime(l.start, i18n.language)}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        {mine ? `${t("tutorJobs.yourRequest")} ` : ""}
        <span className="text-foreground">{t(`tutorJobs.coverStatus.${cover.status}`)}</span>
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

/** Job offers, the job board and cover requests (E16-T10, E19). Offers waiting for an
 * answer give their panel the margin-red rule and count. */
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
    return <Spinner label={t("grid.loading")} />;
  }
  const open = offers.data.filter((o) => o.status === "sent");
  const past = offers.data.filter((o) => o.status !== "sent");
  const shown = [...open, ...past.slice(0, 5)];
  return (
    <div>
      <PortalHeader title={t("tutorJobs.title")} />
      <div className="space-y-6">
        <RuledPanel
          title={t("tutorJobs.offers")}
          titleId="offers-heading"
          rule={open.length ? "margin" : "border"}
          aside={
            open.length ? (
              <span className="font-semibold text-margin tabular-nums">{open.length}</span>
            ) : undefined
          }
          flush
        >
          {shown.length ? (
            <ul className="divide-y divide-border">
              {shown.map((o) => (
                <OfferCard key={o.id} offer={o} />
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("tutorJobs.noOffers")}</PanelEmpty>
          )}
        </RuledPanel>
        <RuledPanel title={t("tutorJobs.board")} titleId="board-heading" flush>
          {postings.data.length ? (
            <ul className="divide-y divide-border">
              {postings.data.map((p) => (
                <PostingCard key={p.id} posting={p} />
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("tutorJobs.noPostings")}</PanelEmpty>
          )}
        </RuledPanel>
        <RuledPanel title={t("tutorJobs.cover")} titleId="cover-heading" flush>
          {cover.data.length ? (
            <ul className="divide-y divide-rule">
              {cover.data.map((c) => (
                <CoverCard key={c.id} cover={c} tutorId={tutorId} />
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("tutorJobs.noCover")}</PanelEmpty>
          )}
        </RuledPanel>
      </div>
    </div>
  );
}
