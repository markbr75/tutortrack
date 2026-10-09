import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, ErrorFallback, SelectField, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { api, usePermission } from "../api";
import { ClientBilling } from "../billing/ClientBilling";
import { InviteButton } from "../portal/InviteButton";
import { RecordActivity } from "../crm/Activity";
import { StudentJobs } from "../jobs/StudentJobs";
import { STUDENT_STATUSES, TUTOR_STATUSES } from "./statuses";

const linkClass = "font-medium underline-offset-2 hover:underline";

function Loading({
  query,
}: {
  query: { isPending: boolean; isError: boolean; refetch: () => unknown };
}) {
  const { t } = useTranslation();
  if (query.isError) {
    return (
      <ErrorFallback
        title={t("errors.generic")}
        retryLabel={t("errors.retry")}
        onRetry={() => void query.refetch()}
      />
    );
  }
  return <Spinner label={t("grid.loading")} />;
}

/** Label/value pairs; empty values are left out. */
function Facts({ items }: { items: [string, ReactNode][] }) {
  const shown = items.filter(([, value]) => value !== null && value !== undefined && value !== "");
  return (
    <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[max-content_1fr]">
      {shown.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-sm text-muted-foreground">{label}</dt>
          <dd className="text-sm">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border p-4">
      <h2 className="mb-3 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** The family page: household, contacts, students and activity (E05-T11). */
export function ClientPage({ clientId }: { clientId: string }) {
  const { t, i18n } = useTranslation();
  const canInvite = usePermission("people.client.edit");
  const canBilling = usePermission("billing.invoice.view");
  const client = useQuery({
    queryKey: ["clients", clientId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/clients/{id}", { params: { path: { id: clientId } } })),
  });
  if (!client.data) return <Loading query={client} />;
  const c = client.data;
  return (
    <article>
      <p className="mb-2 text-sm">
        <Link to="/clients" className={linkClass}>
          {t("people.clients")}
        </Link>
      </p>
      <h1 className="text-2xl font-semibold">{c.display_name}</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        {t(`people.clientType.${c.type ?? "household"}`)} · {t(`people.clientStatus.${c.status}`)}
        {c.archived_at
          ? ` · ${t("people.archivedOn", { when: formatDate(c.archived_at, i18n.language) })}`
          : ""}
      </p>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t("people.contacts")}>
          <ul className="space-y-3">
            {c.contacts.map((contact) => (
              <li key={contact.id}>
                <p className="font-medium">
                  {contact.full_name}
                  {contact.is_primary ? ` · ${t("people.primary")}` : ""}
                  {contact.is_bill_payer ? ` · ${t("people.billPayer")}` : ""}
                </p>
                <p className="text-sm text-muted-foreground">
                  {[
                    t(`people.relationship.${contact.relationship ?? "parent"}`),
                    contact.email,
                    contact.phone || contact.mobile,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {canInvite && contact.email ? (
                  <InviteButton contactId={contact.id} name={contact.full_name} />
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
        <Card title={t("people.students")}>
          <ul className="space-y-3">
            {c.students.map((student) => (
              <li key={student.id}>
                <Link
                  className={linkClass}
                  to="/students/$studentId"
                  params={{ studentId: student.id }}
                >
                  {student.full_name}
                </Link>
                <p className="text-sm text-muted-foreground">
                  {[student.year_group, t(`people.studentStatus.${student.status ?? "active"}`)]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </li>
            ))}
          </ul>
          {c.students.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("people.noStudents")}</p>
          ) : null}
        </Card>
        <Card title={t("people.billing")}>
          <Facts
            items={[
              [t("people.currency"), c.currency],
              [t("people.paymentTerms"), t("people.days", { count: c.payment_terms_days ?? 0 })],
              [t("people.poNumber"), c.po_number],
              [
                t("people.billingAddress"),
                c.billing_address
                  ? [c.billing_address.line1, c.billing_address.city, c.billing_address.postcode]
                      .filter(Boolean)
                      .join(", ")
                  : "",
              ],
            ]}
          />
        </Card>
      </div>
      {canBilling ? <ClientBilling clientId={c.id} currency={c.currency ?? "GBP"} /> : null}
      <RecordActivity target={{ target_type: "people.client", target_id: c.id }} />
    </article>
  );
}

function StatusChanger({
  current,
  statuses,
  prefix,
  onChange,
  pending,
  error,
}: {
  current: string;
  statuses: readonly string[];
  prefix: string;
  onChange: (status: string) => void;
  pending: boolean;
  error: unknown;
}) {
  const { t } = useTranslation();
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const value = new FormData(e.currentTarget).get("status");
        if (typeof value === "string" && value !== current) onChange(value);
      }}
    >
      <SelectField
        name="status"
        label={t("people.status")}
        defaultValue={current}
        options={statuses.map((s) => ({ value: s, label: t(`${prefix}.${s}`) }))}
      />
      <Button type="submit" variant="secondary" disabled={pending}>
        {t("people.changeStatus")}
      </Button>
      {error ? <Alert tone="danger">{t("errors.generic")}</Alert> : null}
    </form>
  );
}

export function StudentPage({ studentId }: { studentId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("people.student.edit");
  const student = useQuery({
    queryKey: ["students", studentId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/students/{id}", { params: { path: { id: studentId } } })),
  });
  const status = useMutation({
    mutationFn: async (value: string) =>
      unwrap(
        await api.POST("/api/v1/students/{id}/status", {
          params: { path: { id: studentId } },
          body: { status: value },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["students"] }),
  });
  if (!student.data) return <Loading query={student} />;
  const s = student.data;
  return (
    <article>
      <p className="mb-2 text-sm">
        <Link to="/students" className={linkClass}>
          {t("people.studentsTitle")}
        </Link>
        {" · "}
        <Link to="/clients/$clientId" params={{ clientId: s.client }} className={linkClass}>
          {t("people.family")}
        </Link>
      </p>
      <h1 className="text-2xl font-semibold">{s.full_name}</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        {t(`people.studentStatus.${s.status ?? "active"}`)}
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t("people.details")}>
          <Facts
            items={[
              [t("people.yearGroup"), s.year_group],
              [t("people.school"), s.school],
              [
                t("people.dateOfBirth"),
                s.date_of_birth ? formatDate(s.date_of_birth, i18n.language) : "",
              ],
              [
                t("people.subjects"),
                (s.subjects ?? [])
                  .map((x) => [x.subject, x.level].filter(Boolean).join(" "))
                  .join(", "),
              ],
              [t("people.goals"), s.goals],
              [t("people.learningNeeds"), s.learning_needs],
            ]}
          />
        </Card>
        {canEdit ? (
          <Card title={t("people.changeStatus")}>
            <StatusChanger
              current={s.status ?? "active"}
              statuses={STUDENT_STATUSES}
              prefix="people.studentStatus"
              onChange={(value) => status.mutate(value)}
              pending={status.isPending}
              error={status.error}
            />
          </Card>
        ) : null}
      </div>
      <div className="mt-4">
        <StudentJobs studentId={s.id} />
      </div>
      <RecordActivity target={{ target_type: "people.student", target_id: s.id }} />
    </article>
  );
}

/** Tutor profile (E05-T11): details, subjects (with approval) and activity. */
export function TutorPage({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("people.tutor.edit");
  const canApprove = usePermission("people.tutor.approve_subjects");
  const tutor = useQuery({
    queryKey: ["tutors", tutorId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/tutors/{id}", { params: { path: { id: tutorId } } })),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["tutors"] });
  const status = useMutation({
    mutationFn: async (value: string) =>
      unwrap(
        await api.POST("/api/v1/tutors/{id}/status", {
          params: { path: { id: tutorId } },
          body: { status: value },
        }),
      ),
    onSuccess: refresh,
  });
  const approve = useMutation({
    mutationFn: async (subjectId: string) =>
      unwrap(
        await api.POST("/api/v1/tutors/{id}/subjects/{subject_id}/approve", {
          params: { path: { id: tutorId, subject_id: subjectId } },
        }),
      ),
    onSuccess: refresh,
  });
  if (!tutor.data) return <Loading query={tutor} />;
  const p = tutor.data;
  return (
    <article>
      <p className="mb-2 text-sm">
        <Link to="/tutors" className={linkClass}>
          {t("people.tutorsTitle")}
        </Link>
      </p>
      <h1 className="text-2xl font-semibold">{p.full_name}</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        {t(`people.tutorStatus.${p.status}`)}
        {p.has_joined ? "" : ` · ${t("people.invitePending")}`}
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t("people.details")}>
          <Facts
            items={[
              [t("people.email"), p.email],
              [t("people.phone"), p.phone],
              [t("people.headline"), p.headline],
              [t("people.payRate"), p.pay_rate_amount],
              [
                t("people.delivery"),
                [
                  p.delivers_online ? t("people.online") : "",
                  p.delivers_in_person ? t("people.inPerson") : "",
                ]
                  .filter(Boolean)
                  .join(", "),
              ],
            ]}
          />
        </Card>
        <Card title={t("people.subjects")}>
          <ul className="space-y-2">
            {p.subjects.map((subject) => (
              <li key={subject.id} className="flex flex-wrap items-center gap-2">
                <span>{[subject.subject, subject.level].filter(Boolean).join(" · ")}</span>
                {subject.approved ? (
                  <span className="text-xs text-muted-foreground">{t("people.approved")}</span>
                ) : canApprove ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={approve.isPending}
                    onClick={() => approve.mutate(subject.id)}
                    aria-label={t("people.approveSubject", { subject: subject.subject })}
                  >
                    {t("people.approve")}
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    {t("people.awaitingApproval")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
        {canEdit ? (
          <Card title={t("people.changeStatus")}>
            <StatusChanger
              current={p.status}
              statuses={TUTOR_STATUSES}
              prefix="people.tutorStatus"
              onChange={(value) => status.mutate(value)}
              pending={status.isPending}
              error={status.error}
            />
          </Card>
        ) : null}
      </div>
      <RecordActivity target={{ target_type: "people.tutor", target_id: p.id }} />
    </article>
  );
}
