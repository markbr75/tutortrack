import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  FactList,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePortalMe } from "../api";
import { PanelEmpty, PanelLoading, PortalHeader } from "../layout/PortalPage";

type Hold = components["schemas"]["BookingHold"];
type Slot = { tutor: string; tutor_name: string; start: string };

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const quiet = "text-muted-foreground hover:text-foreground";

/** Self-booking for families (FR-08-9 on the E08-T14 engine): service → tutor (or any) →
 * free time → hold (the slot is kept for a few minutes) → book (and pay, when the
 * organisation asks for payment at booking). Also lists requests to move lessons that
 * wait for the family's answer. */
export function BookingPage() {
  const { t, i18n } = useTranslation();
  const me = usePortalMe();
  const queryClient = useQueryClient();
  const [service, setService] = useState("");
  const [tutor, setTutor] = useState("");
  const [from, setFrom] = useState(() => isoDate(new Date()));
  const [student, setStudent] = useState("");
  const [promo, setPromo] = useState("");
  const [credit, setCredit] = useState("");
  const [hold, setHold] = useState<Hold | null>(null);
  const services = useQuery({
    queryKey: ["portal", "booking", "services"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/booking/services")),
  });
  const chosen = services.data?.find((s) => s.id === service);
  const to = isoDate(new Date(new Date(from).getTime() + 6 * 86_400_000));
  const slots = useQuery({
    queryKey: ["portal", "booking", "slots", service, tutor, from],
    enabled: Boolean(service),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/portal/booking/slots", {
          params: { query: { service, tutor: tutor || undefined, from, to } },
        }),
      ),
  });
  const students = me.data?.students ?? [];
  const who = student || students[0]?.id || "";
  // E15-T09: a makeup credit (from a cancelled lesson) makes the booking free.
  const credits = useQuery({
    queryKey: ["portal", "makeup-credits"],
    enabled: Boolean(me.data?.features.makeups),
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/makeup-credits")),
  });
  const usable = (credits.data ?? []).filter((c) => c.student === who);
  const take = useMutation({
    mutationFn: async (slot: { start: string; tutor: string }) =>
      unwrap(
        await api.POST("/api/v1/portal/booking/holds", {
          body: {
            service,
            tutor: slot.tutor,
            start: slot.start,
            student: who,
            promo_code: promo,
            makeup_credit: usable.some((c) => c.id === credit) ? credit : null,
          },
        }),
      ),
    onSuccess: setHold,
  });
  const submit = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/portal/booking/holds/{hold_id}/submit", {
          params: { path: { hold_id: id } },
        }),
      ),
    onSuccess: (data) => {
      setHold(data.booking);
      void queryClient.invalidateQueries({ queryKey: ["portal"] });
    },
  });
  const cancel = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/portal/booking/holds/{hold_id}/cancel", {
          params: { path: { hold_id: id } },
        }),
      ),
    onSuccess: () => setHold(null),
  });
  const price = (amount?: { amount: string; currency: string } | null) =>
    amount
      ? new Intl.NumberFormat(i18n.language, {
          style: "currency",
          currency: amount.currency,
        }).format(Number(amount.amount))
      : "";

  return (
    <div>
      <PortalHeader title={t("portalBooking.title")} />
      <div className="space-y-6">
        <RescheduleRequests />
        {hold ? (
          <section aria-live="polite">
            <RuledPanel
              title={`${hold.service_name} · ${formatDateTime(hold.start, i18n.language)}`}
              flush
              footer={
                hold.status === "held" ? (
                  <>
                    <Button onClick={() => submit.mutate(hold.id)} disabled={submit.isPending}>
                      {t("portalBooking.book")}
                    </Button>
                    <Button variant="ghost" className={quiet} onClick={() => cancel.mutate(hold.id)}>
                      {t("portalBooking.changeTime")}
                    </Button>
                  </>
                ) : submit.data?.pay_url ? (
                  <a className={buttonClass()} href={submit.data.pay_url}>
                    {t("portalBooking.payNow")}
                  </a>
                ) : undefined
              }
            >
              <FactList
                items={[
                  [t("portalBooking.tutor"), hold.tutor_name],
                  [t("portal.student"), hold.student_name],
                ]}
              />
              {hold.quote ? (
                <p className="border-t border-rule px-5 py-2.5 text-sm font-semibold tabular-nums">
                  {t("portalBooking.price", { price: price(hold.quote.amount) })}
                  {hold.quote.discounts.length ? ` (${hold.quote.trace.slice(-1)[0] ?? ""})` : ""}
                </p>
              ) : null}
              <div className="border-t border-rule px-5 py-3">
                {hold.status === "held" ? (
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {t("portalBooking.heldUntil", {
                      when: formatDateTime(hold.expires_at, i18n.language),
                    })}
                  </p>
                ) : (
                  <Alert tone={hold.status === "confirmed" ? "success" : "info"}>
                    {t(`portalBooking.status.${hold.status}`)}
                  </Alert>
                )}
              </div>
            </RuledPanel>
          </section>
        ) : (
          <RuledPanel title={t("designS10.findATime")} flush>
            {services.isPending ? (
              <PanelLoading label={t("grid.loading")} />
            ) : !services.data?.length ? (
              <PanelEmpty>{t("portalBooking.noServices")}</PanelEmpty>
            ) : (
              <>
                <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
                  <SelectField
                    label={t("portalBooking.service")}
                    value={service}
                    onChange={(e) => {
                      setService(e.target.value);
                      setTutor("");
                    }}
                    options={[
                      { value: "", label: t("portalBooking.choose") },
                      ...services.data.map((s) => ({
                        value: s.id,
                        label: s.price ? `${s.name} · ${price(s.price)}` : s.name,
                      })),
                    ]}
                  />
                  <SelectField
                    label={t("portalBooking.tutor")}
                    value={tutor}
                    onChange={(e) => setTutor(e.target.value)}
                    options={[
                      { value: "", label: t("portalBooking.anyTutor") },
                      ...(chosen?.tutors ?? []).map((p) => ({ value: p.id, label: p.name })),
                    ]}
                  />
                  {students.length > 1 ? (
                    <SelectField
                      label={t("portal.student")}
                      value={who}
                      onChange={(e) => setStudent(e.target.value)}
                      options={students.map((s) => ({ value: s.id, label: s.name }))}
                    />
                  ) : null}
                  <TextField
                    label={t("portalBooking.weekFrom")}
                    type="date"
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                  />
                  <TextField
                    label={t("portalBooking.promo")}
                    value={promo}
                    onChange={(e) => setPromo(e.target.value)}
                  />
                  {usable.length ? (
                    <SelectField
                      label={t("portalMakeups.label")}
                      hint={t("portalMakeups.hint")}
                      value={credit}
                      onChange={(e) => setCredit(e.target.value)}
                      options={[
                        { value: "", label: t("portalMakeups.none") },
                        ...usable.map((c) => ({
                          value: c.id,
                          label: t("portalMakeups.option", {
                            lesson: c.source_lesson,
                            expires: formatDateTime(c.expires_at, i18n.language, undefined, {
                              dateStyle: "medium",
                            }),
                          }),
                        })),
                      ]}
                    />
                  ) : null}
                </div>
                {service ? (
                  <Times
                    loading={slots.isPending}
                    slots={slots.data ?? []}
                    disabled={take.isPending}
                    onTake={(slot) => take.mutate(slot)}
                  />
                ) : null}
              </>
            )}
          </RuledPanel>
        )}
        {take.error || submit.error ? (
          <Alert tone="danger">{(take.error ?? submit.error)?.message}</Alert>
        ) : null}
      </div>
    </div>
  );
}

/** Free times for the week, one row per day: the day as a caption, its times as secondary
 * buttons in tabular figures (each names its day and tutor for screen readers). */
function Times({
  loading,
  slots,
  disabled,
  onTake,
}: {
  loading: boolean;
  slots: ReadonlyArray<Slot>;
  disabled: boolean;
  onTake: (slot: Slot) => void;
}) {
  const { t, i18n } = useTranslation();
  const day = (iso: string) =>
    formatDateTime(iso, i18n.language, undefined, {
      weekday: "long",
      day: "numeric",
      month: "long",
    });
  const days = new Map<string, Slot[]>();
  for (const slot of slots) {
    const key = day(slot.start);
    days.set(key, [...(days.get(key) ?? []), slot]);
  }
  return (
    <section aria-labelledby="free-times" className="border-t border-border">
      <h3 id="free-times" className="px-5 pt-3.5 pb-1 text-sm font-semibold">
        {t("portalBooking.times")}
      </h3>
      {loading ? (
        <PanelLoading label={t("grid.loading")} />
      ) : !slots.length ? (
        <p className="px-5 pt-1 pb-4 text-sm text-muted-foreground">{t("portalBooking.noTimes")}</p>
      ) : (
        <ul className="divide-y divide-rule" aria-label={t("portalBooking.times")}>
          {[...days.entries()].map(([label, list]) => (
            <li key={label} className="space-y-2 px-5 py-3">
              <p className="text-xs text-muted-foreground">{label}</p>
              <ul className="flex flex-wrap gap-2">
                {list.map((slot) => (
                  <li key={`${slot.tutor}-${slot.start}`}>
                    <Button
                      size="sm"
                      variant="secondary"
                      className="tabular-nums"
                      disabled={disabled}
                      onClick={() => onTake(slot)}
                    >
                      <span className="sr-only">{label} </span>
                      {formatDateTime(slot.start, i18n.language, undefined, {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}{" "}
                      · {slot.tutor_name}
                    </Button>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Requests from tutors to move a lesson, waiting for the family (E08-T13). */
export function RescheduleRequests() {
  const { t, i18n } = useTranslation();
  const me = usePortalMe();
  const queryClient = useQueryClient();
  const enabled = Boolean(me.data?.features.reschedule);
  const requests = useQuery({
    queryKey: ["portal", "reschedule-requests"],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/reschedule-requests")),
  });
  const decide = useMutation({
    mutationFn: async ({ id, approve }: { id: string; approve: boolean }) =>
      unwrap(
        await api.POST("/api/v1/portal/reschedule-requests/{request_id}/decide", {
          params: { path: { request_id: id } },
          body: { approve, choice: 0, note: "", override_conflicts: false },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["portal"] }),
  });
  const waiting = (requests.data ?? []).filter(
    (r) => r.status === "pending" && r.requester === "tutor",
  );
  if (!waiting.length) return null;
  return (
    <RuledPanel title={t("portalBooking.requests")} flush>
      <PanelRows>
        {waiting.map((r) => (
          <PanelRow key={r.id} className="space-y-2">
            <article>
              <p>
                {t("portalBooking.tutorAsks", {
                  lesson: r.lesson_title,
                  from: formatDateTime(r.original_start, i18n.language),
                  to: formatDateTime(r.proposed[0]?.start ?? r.original_start, i18n.language),
                })}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => decide.mutate({ id: r.id, approve: false })}
                >
                  {t("portalBooking.decline")}
                </Button>
                <Button size="sm" onClick={() => decide.mutate({ id: r.id, approve: true })}>
                  {t("portalBooking.accept")}
                </Button>
              </div>
            </article>
          </PanelRow>
        ))}
      </PanelRows>
    </RuledPanel>
  );
}
