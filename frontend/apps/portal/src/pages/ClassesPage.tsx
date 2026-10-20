import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePortalMe } from "../api";

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
  return (
    <section className="space-y-8 p-4">
      <h1 className="text-2xl font-semibold">{t("portalCourses.title")}</h1>
      {offers.length ? (
        <section aria-labelledby="next-term" className="space-y-2">
          <h2 id="next-term" className="text-lg font-semibold">
            {t("portalCourses.nextTerm")}
          </h2>
          <ul className="space-y-2">
            {offers.map((o) => (
              <li key={o.id} className="rounded-md border border-border p-3 text-sm">
                <p className="font-medium">
                  {o.student_name}: {o.course_name} · {o.class_name} · {o.term}
                </p>
                <p>{t("portalCourses.answerBy", { date: formatDateTime(o.deadline) })}</p>
                <p role="status">{t(`portalCourses.offerStatus.${o.status}`)}</p>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" onClick={() => answer.mutate({ id: o.id, confirm: true })}>
                    {t("portalCourses.keep")}
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => answer.mutate({ id: o.id, confirm: false })}
                  >
                    {t("portalCourses.leave")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
          {answer.error ? <Alert tone="danger">{answer.error.message}</Alert> : null}
        </section>
      ) : null}
      <section aria-labelledby="my-classes" className="space-y-2">
        <h2 id="my-classes" className="text-lg font-semibold">
          {t("portalCourses.myClasses")}
        </h2>
        {!current.length ? <p className="text-sm">{t("portalCourses.none")}</p> : null}
        <ul className="space-y-2">
          {current.map((e) => (
            <li key={e.id} className="rounded-md border border-border p-3 text-sm">
              <p className="font-medium">
                {e.student_name}: {e.course_name} · {e.class_name}
              </p>
              <p>
                {weekdayNames(e.weekdays, i18n.language)} {e.start_time} · {e.term} ·{" "}
                {formatDate(e.start_date)}
              </p>
              <p role="status">{t(`portalCourses.status.${e.status}`)}</p>
              {e.status === "pending_payment" ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {e.hold_expires_at ? (
                    <span>
                      {t("portalCourses.heldUntil", { date: formatDateTime(e.hold_expires_at) })}
                    </span>
                  ) : null}
                  {e.pay_url ? (
                    <a className="underline" href={e.pay_url}>
                      {t("portalCourses.pay")}
                    </a>
                  ) : null}
                  <Button size="sm" variant="secondary" onClick={() => giveUp.mutate(e.id)}>
                    {t("portalCourses.giveUp")}
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
      {waitlist.length ? (
        <section aria-labelledby="waitlist" className="space-y-2">
          <h2 id="waitlist" className="text-lg font-semibold">
            {t("portalCourses.waitlist")}
          </h2>
          <ul className="space-y-2">
            {waitlist.map((w) => (
              <li key={w.id} className="rounded-md border border-border p-3 text-sm">
                <p className="font-medium">
                  {w.student_name}: {w.course_name} · {w.class_name}
                </p>
                <p>
                  {w.status === "offered"
                    ? t("portalCourses.offered")
                    : t("portalCourses.position", { position: w.position })}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-labelledby="browse" className="space-y-2">
        <h2 id="browse" className="text-lg font-semibold">
          {t("portalCourses.browse")}
        </h2>
        {!catalogue.data.classes.length ? (
          <p className="text-sm">{t("portalCourses.noneOpen")}</p>
        ) : null}
        <ul className="space-y-3">
          {catalogue.data.classes.map((c) => (
            <ClassCard key={c.id} item={c} terms={catalogue.data.terms} onDone={refresh} />
          ))}
        </ul>
      </section>
    </section>
  );
}

function ClassCard({
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
  return (
    <li className="rounded-md border border-border p-3 text-sm">
      <article aria-labelledby={headingId} className="space-y-1">
        <h3 id={headingId} className="font-semibold">
          {item.course.name}: {item.name}
        </h3>
        {item.course.description ? <p>{item.course.description}</p> : null}
        <p>
          {weekdayNames(item.weekdays, i18n.language)} {item.start_time} · {item.term} ·{" "}
          {formatDate(item.start_date)}
          {item.location ? ` · ${item.location}` : ""}
        </p>
        <p>
          {item.price} ({item.pricing_label}) ·{" "}
          {item.full
            ? t("portalCourses.full")
            : t("portalCourses.placesLeft", { count: item.places_left })}
        </p>
        {item.min_age !== null && item.max_age !== null ? (
          <p>{t("portalCourses.ages", { min: item.min_age, max: item.max_age })}</p>
        ) : null}
        {item.year_groups.length ? (
          <p>{t("portalCourses.years", { years: item.year_groups.join(", ") })}</p>
        ) : null}
        {done ? (
          <p role="status">{done}</p>
        ) : (
          <div className="flex flex-wrap items-end gap-2 pt-2">
            {students.length > 1 ? (
              <SelectField
                label={t("portalCourses.who")}
                value={who}
                onChange={(e) => setStudent(e.target.value)}
                options={students.map((s) => ({ value: s.id, label: s.name }))}
              />
            ) : null}
            {terms ? (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={accepted}
                  onChange={(e) => setAccepted(e.target.checked)}
                />
                {t("portalCourses.acceptTerms")}
              </label>
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
          <details className="text-xs text-muted-foreground">
            <summary>{t("portalCourses.terms")}</summary>
            <p className="whitespace-pre-line">{terms}</p>
          </details>
        ) : null}
        {enrol.error ? <Alert tone="danger">{enrol.error.message}</Alert> : null}
      </article>
    </li>
  );
}
