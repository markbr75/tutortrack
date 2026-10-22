import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  Disclosure,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePortalMe } from "../api";
import { CheckField, PanelEmpty, PortalHeader, Word } from "../layout/PortalPage";

type PublicClass = components["schemas"]["PublicClass"];

function weekdayNames(days: number[], locale: string): string {
  const monday = new Date(Date.UTC(2024, 0, 1));
  return days
    .map((d) =>
      new Date(monday.getTime() + d * 86_400_000).toLocaleDateString(locale, {
        weekday: "long",
        timeZone: "UTC",
      }),
    )
    .join(", ");
}

const quiet = "text-muted-foreground hover:text-foreground";

/** Group classes for families (E20 on the portal): their classes (with payment for a held
 * place), waitlist positions, next term's re-enrolment questions and classes to join. */
export function ClassesPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const mine = useQuery({
    queryKey: ["portal", "courses"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/courses")),
  });
  const catalogue = useQuery({
    queryKey: ["portal", "classes"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/classes")),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["portal"] });
  const answer = useMutation({
    mutationFn: async ({ id, confirm }: { id: string; confirm: boolean }) =>
      unwrap(
        await api.POST("/api/v1/portal/rollover-offers/{offer_id}", {
          params: { path: { offer_id: id } },
          body: { confirm },
        }),
      ),
    onSuccess: refresh,
  });
  const giveUp = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/portal/enrolments/{enrolment_id}/cancel", {
          params: { path: { enrolment_id: id } },
        }),
      ),
    onSuccess: refresh,
  });
  if (!mine.data || !catalogue.data) {
    return <Spinner label={t("grid.loading")} />;
  }
  const { enrolments, waitlist, rollover_offers: offers } = mine.data;
  const current = enrolments.filter((e) =>
    ["pending_payment", "enrolled", "trial"].includes(e.status),
  );
  const when = (days: number[], time: string) => `${weekdayNames(days, i18n.language)} ${time}`;
  return (
    <div>
      <PortalHeader title={t("portalCourses.title")} />
      <div className="space-y-6">
        {offers.length ? (
          <RuledPanel title={t("portalCourses.nextTerm")} flush>
            <PanelRows>
              {offers.map((o) => (
                <PanelRow key={o.id} className="space-y-2">
                  <div>
                    <p className="font-medium">
                      {o.student_name}: {o.course_name} · {o.class_name} · {o.term}
                    </p>
                    <p className="text-xs text-muted-foreground tabular-nums">
                      {t("portalCourses.answerBy", {
                        date: formatDateTime(o.deadline, i18n.language),
                      })}{" "}
                      <span role="status" className="text-foreground">
                        {t(`portalCourses.offerStatus.${o.status}`)}
                      </span>
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => answer.mutate({ id: o.id, confirm: false })}
                    >
                      {t("portalCourses.leave")}
                    </Button>
                    <Button size="sm" onClick={() => answer.mutate({ id: o.id, confirm: true })}>
                      {t("portalCourses.keep")}
                    </Button>
                  </div>
                </PanelRow>
              ))}
            </PanelRows>
            {answer.error ? (
              <div className="px-5 pb-4">
                <Alert tone="danger">{answer.error.message}</Alert>
              </div>
            ) : null}
          </RuledPanel>
        ) : null}
        <RuledPanel title={t("portalCourses.myClasses")} flush>
          {current.length ? (
            <PanelRows>
              {current.map((e) => (
                <PanelRow key={e.id} className="space-y-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                    <div className="min-w-0">
                      <p className="font-medium">
                        {e.student_name}: {e.course_name} · {e.class_name}
                      </p>
                      <p className="text-xs text-muted-foreground tabular-nums">
                        {when(e.weekdays, e.start_time)} · {e.term} ·{" "}
                        {formatDate(e.start_date, i18n.language)}
                      </p>
                    </div>
                    <p role="status" className="text-sm">
                      {t(`portalCourses.status.${e.status}`)}
                    </p>
                  </div>
                  {e.status === "pending_payment" ? (
                    <div className="flex flex-wrap items-center gap-2">
                      {e.pay_url ? (
                        <a className={buttonClass({ size: "sm" })} href={e.pay_url}>
                          {t("portalCourses.pay")}
                        </a>
                      ) : null}
                      <Button
                        size="sm"
                        variant="ghost"
                        className={quiet}
                        onClick={() => giveUp.mutate(e.id)}
                      >
                        {t("portalCourses.giveUp")}
                      </Button>
                      {e.hold_expires_at ? (
                        <span className="basis-full text-xs text-muted-foreground tabular-nums">
                          {t("portalCourses.heldUntil", {
                            date: formatDateTime(e.hold_expires_at, i18n.language),
                          })}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </PanelRow>
              ))}
            </PanelRows>
          ) : (
            <PanelEmpty>{t("portalCourses.none")}</PanelEmpty>
          )}
        </RuledPanel>
        {waitlist.length ? (
          <RuledPanel title={t("portalCourses.waitlist")} flush>
            <PanelRows>
              {waitlist.map((w) => (
                <PanelRow key={w.id}>
                  <p className="font-medium">
                    {w.student_name}: {w.course_name} · {w.class_name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {w.status === "offered"
                      ? t("portalCourses.offered")
                      : t("portalCourses.position", { position: w.position })}
                  </p>
                </PanelRow>
              ))}
            </PanelRows>
          </RuledPanel>
        ) : null}
        <RuledPanel title={t("portalCourses.browse")} flush>
          {catalogue.data.classes.length ? (
            <ul className="divide-y divide-rule">
              {catalogue.data.classes.map((c) => (
                <ClassRow key={c.id} item={c} terms={catalogue.data.terms} onDone={refresh} />
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("portalCourses.noneOpen")}</PanelEmpty>
          )}
        </RuledPanel>
      </div>
    </div>
  );
}

/** A class to join: what, when and where, the price and places in words, then who joins and
 * the one action (enrol, or join the waitlist when full), with the terms folded away. */
function ClassRow({
  item,
  terms,
  onDone,
}: {
  item: PublicClass;
  terms: string;
  onDone: () => void;
}) {
  const { t, i18n } = useTranslation();
  const me = usePortalMe();
  const students = me.data?.students ?? [];
  const [student, setStudent] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [done, setDone] = useState("");
  const who = student || students[0]?.id || "";
  const whoName = students.find((s) => s.id === who)?.name ?? "";
  const enrol = useMutation({
    mutationFn: async (waitlist: boolean) =>
      unwrap(
        await api.POST("/api/v1/portal/enrol", {
          body: {
            group_class: item.id,
            student: who,
            accept_terms: accepted,
            join_waitlist: waitlist,
          },
        }),
      ),
    onSuccess: (data, waitlist) => {
      setDone(
        waitlist
          ? t("portalCourses.waitlisted", { student: whoName })
          : t("portalCourses.enrolled", { student: whoName }),
      );
      if (data && "pay_url" in data && data.pay_url) window.location.assign(data.pay_url);
      onDone();
    },
  });
  const headingId = `class-${item.id}`;
  const facts = [
    item.min_age !== null && item.max_age !== null
      ? t("portalCourses.ages", { min: item.min_age, max: item.max_age })
      : "",
    item.year_groups.length ? t("portalCourses.years", { years: item.year_groups.join(", ") }) : "",
  ].filter(Boolean);
  return (
    <li className="px-5 py-3.5">
      <article aria-labelledby={headingId} className="space-y-3 text-sm">
        <div className="space-y-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4">
            <h3 id={headingId} className="font-semibold">
              {item.course.name}: {item.name}
            </h3>
            <p className="font-semibold tabular-nums">
              {item.price} <span className="font-normal text-muted-foreground">({item.pricing_label})</span>
            </p>
          </div>
          <p className="text-xs text-muted-foreground tabular-nums">
            {weekdayNames(item.weekdays, i18n.language)} {item.start_time} · {item.term} ·{" "}
            {formatDate(item.start_date, i18n.language)}
            {item.location ? ` · ${item.location}` : ""}
          </p>
          <p>
            {item.full ? (
              <Word tone="muted">{t("portalCourses.full")}</Word>
            ) : (
              t("portalCourses.placesLeft", { count: item.places_left })
            )}
            {facts.length ? ` · ${facts.join(" · ")}` : ""}
          </p>
          {item.course.description ? (
            <p className="text-muted-foreground">{item.course.description}</p>
          ) : null}
        </div>
        {done ? (
          <p role="status" className="font-medium">
            {done}
          </p>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            {students.length > 1 ? (
              <SelectField
                size="sm"
                label={t("portalCourses.who")}
                value={who}
                onChange={(e) => setStudent(e.target.value)}
                options={students.map((s) => ({ value: s.id, label: s.name }))}
              />
            ) : null}
            {terms ? (
              <CheckField
                className="min-h-9 items-center"
                label={t("portalCourses.acceptTerms")}
                checked={accepted}
                onChange={(e) => setAccepted(e.target.checked)}
              />
            ) : null}
            {item.full ? (
              item.waitlist ? (
                <Button size="sm" variant="secondary" onClick={() => enrol.mutate(true)}>
                  {t("portalCourses.joinWaitlist")}
                </Button>
              ) : null
            ) : (
              <Button
                size="sm"
                disabled={!who || (Boolean(terms) && !accepted)}
                onClick={() => enrol.mutate(false)}
              >
                {t("portalCourses.enrol", { student: whoName })}
              </Button>
            )}
          </div>
        )}
        {terms ? (
          <Disclosure summary={t("portalCourses.terms")}>
            <p className="text-xs whitespace-pre-line text-muted-foreground">{terms}</p>
          </Disclosure>
        ) : null}
        {enrol.error ? <Alert tone="danger">{enrol.error.message}</Alert> : null}
      </article>
    </li>
  );
}
