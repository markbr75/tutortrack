import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  ErrorFallback,
  NamePlate,
  Panel,
  PanelRow,
  PanelRows,
  SelectField,
  Spinner,
  Tabs,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { PayProfileCard } from "../payroll/PayProfileCard";
import { BackgroundChecksCard } from "../recruitment/BackgroundChecksCard";
import { TutorOffboardingCard, TutorPerformanceCard } from "../recruitment/HiringPages";
import { TutorComplianceCard } from "../recruitment/RecruitmentPages";
import { api, usePermission } from "../api";
import { ClientBilling } from "../billing/ClientBilling";
import {
  BackSeparator,
  HeaderReveal,
  RecordHeader,
  RecordLayout,
} from "../components/RecordHeader";
import { InviteButton } from "../portal/InviteButton";
import { RecordActivity } from "../crm/Activity";
import { StudentJobs } from "../jobs/StudentJobs";
import { StudentPrivacyPanel } from "../safeguarding/SafeguardingPages";
import {
  addressFields,
  addressValues,
  useEditing,
  withAddress,
  type DetailField,
  type Value,
} from "./details";
import { DetailsForm, EditableDetails, EditButton } from "./EditableDetails";
import { StudentMatchingCard, TutorMatchingCard } from "./MatchingProfileCard";
import { STUDENT_STATUSES, TUTOR_STATUSES } from "./statuses";

const linkClass = "font-medium underline-offset-2 hover:underline";
const textLink = "font-medium text-link underline-offset-2 hover:underline";

/** FR-05-13: "Merge with another record", a small secondary action in the record's header. */
function MergeLink({ entity, id }: { entity: "clients" | "students"; id: string }) {
  const { t } = useTranslation();
  const canMerge = usePermission("people.merge");
  if (!canMerge) return null;
  return (
    <Link
      className={buttonClass({ variant: "secondary", size: "sm" })}
      to="/people/merge/$entity/$sourceId"
      params={{ entity, sourceId: id }}
    >
      {t("peopleTools.merge.mergeWith")}
    </Link>
  );
}

/** The banner on a merged (archived) record, pointing at the record that was kept. */
function MergedBanner({
  entity,
  mergedInto,
}: {
  entity: "clients" | "students";
  mergedInto?: string | null;
}) {
  const { t } = useTranslation();
  if (!mergedInto) return null;
  return (
    <Alert tone="info" className="mb-6">
      {t("peopleTools.merge.mergedInto")}{" "}
      {entity === "clients" ? (
        <Link className={textLink} to="/clients/$clientId" params={{ clientId: mergedInto }}>
          {t("peopleTools.merge.openSurvivor")}
        </Link>
      ) : (
        <Link className={textLink} to="/students/$studentId" params={{ studentId: mergedInto }}>
          {t("peopleTools.merge.openSurvivor")}
        </Link>
      )}
    </Alert>
  );
}

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

/** The family page: household, contacts, students, billing and activity (E05-T11). */
export function ClientPage({ clientId }: { clientId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canInvite = usePermission("people.client.edit");
  const canEdit = canInvite;
  const canBilling = usePermission("billing.invoice.view");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["clients"] });
  const client = useQuery({
    queryKey: ["clients", clientId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/clients/{id}", { params: { path: { id: clientId } } })),
  });
  if (!client.data) return <Loading query={client} />;
  const c = client.data;
  const address = c.billing_address
    ? [c.billing_address.line1, c.billing_address.city, c.billing_address.postcode]
        .filter(Boolean)
        .join(", ")
    : "";
  return (
    <article>
      <RecordHeader
        back={<Link to="/clients">{t("people.clients")}</Link>}
        title={c.display_name}
        description={[
          t(`people.clientType.${c.type ?? "household"}`),
          t(`people.clientStatus.${c.status}`),
          c.archived_at
            ? t("people.archivedOn", { when: formatDate(c.archived_at, i18n.language) })
            : "",
        ]
          .filter(Boolean)
          .join(" · ")}
        actions={c.merged_into ? null : <MergeLink entity="clients" id={c.id} />}
      />
      <MergedBanner entity="clients" mergedInto={c.merged_into} />
      <RecordLayout
        main={
          <>
            {canBilling ? <ClientBilling clientId={c.id} currency={c.currency ?? "GBP"} /> : null}
            <RecordActivity target={{ target_type: "people.client", target_id: c.id }} />
          </>
        }
        side={
          <>
            <Panel title={t("people.contacts")} flush>
              {c.contacts.length ? (
                <PanelRows>
                  {c.contacts.map((contact) => (
                    <ContactRow
                      key={contact.id}
                      contact={contact}
                      canEdit={canEdit}
                      onSaved={refresh}
                    />
                  ))}
                </PanelRows>
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  {t("designS5.client.noContacts")}
                </p>
              )}
            </Panel>
            <Panel title={t("people.students")} flush>
              {c.students.length ? (
                <PanelRows>
                  {c.students.map((student) => (
                    <PanelRow key={student.id}>
                      <NamePlate
                        name={
                          <Link
                            className={linkClass}
                            to="/students/$studentId"
                            params={{ studentId: student.id }}
                          >
                            {student.full_name}
                          </Link>
                        }
                        context={[
                          student.year_group,
                          t(`people.studentStatus.${student.status ?? "active"}`),
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      />
                    </PanelRow>
                  ))}
                </PanelRows>
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">{t("people.noStudents")}</p>
              )}
            </Panel>
            <EditableDetails
              title={t("designS5.client.billingDetails")}
              editLabel={t("editDetails.client", { name: c.display_name })}
              canEdit={canEdit}
              record={{ ...c, ...addressValues(c.billing_address) }}
              fields={[
                { name: "display_name", label: t("people.name"), wide: true },
                {
                  name: "payment_terms_days",
                  label: t("editDetails.paymentTermsDays"),
                  kind: "number",
                },
                { name: "po_number", label: t("people.poNumber") },
                ...addressFields(t),
              ]}
              save={async (changes) =>
                unwrap(
                  await api.PATCH("/api/v1/clients/{id}", {
                    params: { path: { id: c.id } },
                    body: withAddress(
                      changes,
                      "billing_address_input",
                      c.billing_address,
                    ) as Patch<"Client">,
                  }),
                )
              }
              onSaved={refresh}
              facts={[
                [t("people.currency"), c.currency],
                [t("people.paymentTerms"), t("people.days", { count: c.payment_terms_days ?? 0 })],
                [t("people.poNumber"), c.po_number],
                [t("people.billingAddress"), address],
              ]}
            />
          </>
        }
      />
    </article>
  );
}

type ContactRecord = components["schemas"]["Contact"];
/** A PATCH body; the details form only sends fields from the record it was given. */
type Patch<T extends "Client" | "Contact" | "Student" | "Tutor"> =
  components["schemas"][`Patched${T}Request`];

/** One contact on the family page; "Edit" swaps the row for their contact details. */
function ContactRow({
  contact,
  canEdit,
  onSaved,
}: {
  contact: ContactRecord;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const edit = useEditing();
  const label = t("editDetails.contact", { name: contact.full_name });
  const fields: DetailField[] = [
    { name: "first_name", label: t("people.firstName"), autoComplete: "off" },
    { name: "last_name", label: t("people.lastName"), autoComplete: "off" },
    { name: "email", label: t("people.email"), kind: "email", autoComplete: "off", wide: true },
    { name: "phone", label: t("people.phone"), kind: "tel", autoComplete: "off" },
    { name: "mobile", label: t("editDetails.mobile"), kind: "tel", autoComplete: "off" },
  ];
  if (edit.open) {
    return (
      <PanelRow className="p-0">
        <DetailsForm
          label={label}
          fields={fields}
          record={contact}
          save={async (changes: Record<string, Value>) =>
            unwrap(
              await api.PATCH("/api/v1/contacts/{id}", {
                params: { path: { id: contact.id } },
                body: changes as Patch<"Contact">,
              }),
            )
          }
          onDone={(saved) => {
            if (saved) onSaved();
            edit.stop();
          }}
        />
      </PanelRow>
    );
  }
  return (
    <PanelRow>
      <NamePlate
        name={contact.full_name}
        context={[
          t(`people.relationship.${contact.relationship ?? "parent"}`),
          contact.is_primary ? t("people.primary") : "",
          contact.is_bill_payer ? t("people.billPayer") : "",
          contact.email,
          contact.phone || contact.mobile,
        ]
          .filter(Boolean)
          .join(" · ")}
        aside={
          canEdit ? (
            <span className="flex flex-wrap justify-end gap-2">
              <EditButton buttonRef={edit.buttonRef} name={label} onClick={edit.start} />
              {contact.email ? (
                <InviteButton contactId={contact.id} name={contact.full_name} variant="secondary" />
              ) : null}
            </span>
          ) : null
        }
      />
    </PanelRow>
  );
}

/** "Change status" in the record header: opens a compact select and the confirming button. */
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
  onChange: (status: string, done: () => void) => void;
  pending: boolean;
  error: unknown;
}) {
  const { t } = useTranslation();
  return (
    <>
      <HeaderReveal label={t("people.changeStatus")}>
        {(close) => (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const value = new FormData(e.currentTarget).get("status");
              if (typeof value === "string" && value !== current) onChange(value, close);
              else close();
            }}
          >
            <SelectField
              name="status"
              label={t("people.status")}
              hideLabel
              size="sm"
              defaultValue={current}
              options={statuses.map((s) => ({ value: s, label: t(`${prefix}.${s}`) }))}
            />
            <Button type="submit" size="sm" loading={pending}>
              {t("people.changeStatus")}
            </Button>
          </form>
        )}
      </HeaderReveal>
      {error ? (
        <Alert tone="danger" className="basis-full">
          {t("errors.generic")}
        </Alert>
      ) : null}
    </>
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
      <RecordHeader
        back={
          <>
            <Link to="/students">{t("people.studentsTitle")}</Link>
            <BackSeparator />
            <Link to="/clients/$clientId" params={{ clientId: s.client }}>
              {t("people.family")}
            </Link>
          </>
        }
        title={s.full_name ?? ""}
        description={[s.year_group, t(`people.studentStatus.${s.status ?? "active"}`)]
          .filter(Boolean)
          .join(" · ")}
        actions={
          <>
            {canEdit ? (
              <StatusChanger
                current={s.status ?? "active"}
                statuses={STUDENT_STATUSES}
                prefix="people.studentStatus"
                onChange={(value, done) => status.mutate(value, { onSuccess: done })}
                pending={status.isPending}
                error={status.error}
              />
            ) : null}
            {s.merged_into ? null : <MergeLink entity="students" id={s.id} />}
          </>
        }
      />
      <MergedBanner entity="students" mergedInto={s.merged_into} />
      <RecordLayout
        main={
          <>
            <StudentJobs studentId={s.id} />
            <StudentPrivacyPanel studentId={s.id} />
            <RecordActivity target={{ target_type: "people.student", target_id: s.id }} />
          </>
        }
        side={
          <>
            <EditableDetails
              title={t("people.details")}
              editLabel={t("editDetails.student", { name: s.full_name ?? "" })}
              canEdit={canEdit}
              record={s}
              fields={[
                { name: "first_name", label: t("people.firstName"), autoComplete: "off" },
                { name: "last_name", label: t("people.lastName"), autoComplete: "off" },
                {
                  name: "preferred_name",
                  label: t("editDetails.preferredName"),
                  autoComplete: "off",
                },
                { name: "year_group", label: t("people.yearGroup") },
                { name: "school", label: t("people.school"), wide: true },
                { name: "date_of_birth", label: t("people.dateOfBirth"), kind: "date" },
                { name: "goals", label: t("people.goals"), kind: "textarea" },
                { name: "learning_needs", label: t("people.learningNeeds"), kind: "textarea" },
              ]}
              save={async (changes) =>
                unwrap(
                  await api.PATCH("/api/v1/students/{id}", {
                    params: { path: { id: s.id } },
                    body: changes as Patch<"Student">,
                  }),
                )
              }
              onSaved={() => {
                void queryClient.invalidateQueries({ queryKey: ["students"] });
                void queryClient.invalidateQueries({ queryKey: ["clients"] });
              }}
              none={t("designS5.noDetails")}
              facts={[
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
            <StudentMatchingCard student={s} />
          </>
        }
      />
    </article>
  );
}

type TutorTab = "subjects" | "pay" | "compliance" | "performance";

/** Tutor profile (E05-T11): subjects (with approval), pay, compliance, performance and
 * activity in the work area; details, matching profile and status alongside. */
export function TutorPage({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("people.tutor.edit");
  const canApprove = usePermission("people.tutor.approve_subjects");
  const canPay = usePermission("payroll.view");
  const canCompliance = usePermission("compliance.view");
  const canSeePerformance = usePermission("recruitment.performance.view");
  const canOffboard = usePermission("recruitment.offboarding.manage");
  const canPerformance = canSeePerformance || canOffboard;
  const [tab, setTab] = useState<TutorTab>("subjects");
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
  const tabs: { key: TutorTab; label: string }[] = [
    { key: "subjects", label: t("people.subjects") },
    ...(canPay ? [{ key: "pay" as const, label: t("designS5.tutor.pay") }] : []),
    ...(canCompliance
      ? [{ key: "compliance" as const, label: t("designS5.tutor.compliance") }]
      : []),
    ...(canPerformance
      ? [{ key: "performance" as const, label: t("designS5.tutor.performance") }]
      : []),
  ];
  const subjects = (
    <Panel title={t("people.subjects")} flush>
      {p.subjects.length ? (
        <PanelRows>
          {p.subjects.map((subject) => (
            <PanelRow
              key={subject.id}
              className="flex flex-wrap items-center justify-between gap-2"
            >
              <span>{[subject.subject, subject.level].filter(Boolean).join(" · ")}</span>
              {subject.approved ? (
                <span className="text-muted-foreground">{t("people.approved")}</span>
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
                <span className="text-muted-foreground">{t("people.awaitingApproval")}</span>
              )}
            </PanelRow>
          ))}
        </PanelRows>
      ) : (
        <p className="px-5 py-4 text-sm text-muted-foreground">{t("designS5.tutor.noSubjects")}</p>
      )}
    </Panel>
  );
  const current = tabs.some((x) => x.key === tab) ? tab : "subjects";
  return (
    <article>
      <RecordHeader
        back={<Link to="/tutors">{t("people.tutorsTitle")}</Link>}
        title={p.full_name}
        description={[
          t(`people.tutorStatus.${p.status}`),
          p.has_joined ? "" : t("people.invitePending"),
        ]
          .filter(Boolean)
          .join(" · ")}
        actions={
          canEdit ? (
            <StatusChanger
              current={p.status}
              statuses={TUTOR_STATUSES}
              prefix="people.tutorStatus"
              onChange={(value, done) => status.mutate(value, { onSuccess: done })}
              pending={status.isPending}
              error={status.error}
            />
          ) : null
        }
      />
      <RecordLayout
        main={
          <>
            {tabs.length > 1 ? (
              <Tabs
                label={t("designS5.tutor.sections")}
                tabs={tabs}
                value={current}
                onChange={setTab}
              >
                <div className="space-y-6 [&>section]:rounded-xl [&>section]:bg-surface">
                  {current === "subjects" ? subjects : null}
                  {current === "pay" ? <PayProfileCard tutorId={tutorId} /> : null}
                  {current === "compliance" ? (
                    <>
                      <TutorComplianceCard tutorId={tutorId} />
                      <BackgroundChecksCard tutorId={tutorId} />
                    </>
                  ) : null}
                  {current === "performance" ? (
                    <>
                      <TutorPerformanceCard tutorId={tutorId} />
                      <TutorOffboardingCard tutorId={tutorId} />
                    </>
                  ) : null}
                </div>
              </Tabs>
            ) : (
              subjects
            )}
            <RecordActivity target={{ target_type: "people.tutor", target_id: p.id }} />
          </>
        }
        side={
          <>
            <EditableDetails
              title={t("people.details")}
              editLabel={t("editDetails.tutor", { name: p.full_name })}
              canEdit={canEdit}
              record={p}
              fields={[
                { name: "first_name", label: t("people.firstName"), autoComplete: "off" },
                { name: "last_name", label: t("people.lastName"), autoComplete: "off" },
                {
                  name: "display_name",
                  label: t("editDetails.displayName"),
                  hint: t("editDetails.displayNameHint"),
                  autoComplete: "off",
                  wide: true,
                },
                // A tutor who has joined signs in with their email: it isn't edited here.
                ...(p.has_joined
                  ? []
                  : [
                      {
                        name: "email",
                        label: t("people.email"),
                        kind: "email" as const,
                        autoComplete: "off",
                        wide: true,
                      },
                    ]),
                { name: "phone", label: t("people.phone"), kind: "tel", autoComplete: "off" },
                { name: "pay_rate_amount", label: t("people.payRate"), kind: "number" },
                { name: "headline", label: t("people.headline"), wide: true },
                { name: "bio_public", label: t("editDetails.bioPublic"), kind: "textarea" },
                { name: "bio_private", label: t("editDetails.bioPrivate"), kind: "textarea" },
                { name: "travel_radius_km", label: t("editDetails.travelRadius"), kind: "number" },
                {
                  name: "delivers_online",
                  label: t("editDetails.deliversOnline"),
                  kind: "checkbox",
                },
                {
                  name: "delivers_in_person",
                  label: t("editDetails.deliversInPerson"),
                  kind: "checkbox",
                },
              ]}
              save={async (changes) =>
                unwrap(
                  await api.PATCH("/api/v1/tutors/{id}", {
                    params: { path: { id: p.id } },
                    body: { ...changes, invite: false } as Patch<"Tutor">,
                  }),
                )
              }
              onSaved={() => {
                refresh();
                void queryClient.invalidateQueries({ queryKey: ["me"] });
              }}
              none={t("designS5.noDetails")}
              facts={[
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
            <TutorMatchingCard tutor={p} />
          </>
        }
      />
    </article>
  );
}
