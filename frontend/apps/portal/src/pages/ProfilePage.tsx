import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";

type Contact = components["schemas"]["PortalContact"];
type Student = components["schemas"]["PortalStudent"];
const FLAGS = [
  "receives_reminders",
  "receives_invoices",
  "receives_reports",
  "receives_marketing",
] as const;

function ContactForm({ contact }: { contact: Contact }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form, setForm] = useState(contact);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/portal/profile/contacts/{contact_id}", {
          params: { path: { contact_id: contact.id } },
          body: {
            first_name: form.first_name,
            last_name: form.last_name,
            phone: form.phone,
            mobile: form.mobile,
            receives_reminders: form.receives_reminders,
            receives_invoices: form.receives_invoices,
            receives_reports: form.receives_reports,
            receives_marketing: form.receives_marketing,
          },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["portal", "profile"] }),
  });
  return (
    <form
      className="space-y-3 rounded-lg border border-border p-4"
      aria-label={t("portal.yourDetails")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h2 className="font-semibold">{t("portal.yourDetails")}</h2>
      <p className="text-sm text-muted-foreground">{form.email}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <TextField
          label={t("portal.firstName")}
          value={form.first_name}
          onChange={(e) => setForm({ ...form, first_name: e.target.value })}
        />
        <TextField
          label={t("portal.lastName")}
          value={form.last_name ?? ""}
          onChange={(e) => setForm({ ...form, last_name: e.target.value })}
        />
        <TextField
          label={t("portal.phone")}
          value={form.phone ?? ""}
          onChange={(e) => setForm({ ...form, phone: e.target.value })}
        />
        <TextField
          label={t("portal.mobile")}
          value={form.mobile ?? ""}
          onChange={(e) => setForm({ ...form, mobile: e.target.value })}
        />
      </div>
      <fieldset className="space-y-1 text-sm">
        <legend className="font-medium">{t("portal.whatToReceive")}</legend>
        {FLAGS.map((flag) => (
          <label key={flag} className="flex items-center gap-2">
            <input
              type="checkbox"
              className="size-4"
              checked={Boolean(form[flag])}
              onChange={(e) => setForm({ ...form, [flag]: e.target.checked })}
            />
            {t(`portal.flags.${flag}`)}
          </label>
        ))}
      </fieldset>
      {save.isSuccess ? <Alert tone="success">{t("portal.saved")}</Alert> : null}
      <Button type="submit" disabled={save.isPending}>
        {t("portal.save")}
      </Button>
    </form>
  );
}

function StudentForm({ student }: { student: Student }) {
  const { t } = useTranslation();
  const needsId = useId();
  const [form, setForm] = useState(student);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/portal/profile/students/{student_id}", {
          params: { path: { student_id: student.id } },
          body: {
            preferred_name: form.preferred_name,
            school: form.school,
            year_group: form.year_group,
            learning_needs: form.learning_needs,
          },
        }),
      ),
  });
  return (
    <form
      className="space-y-3 rounded-lg border border-border p-4"
      aria-label={`${student.first_name} ${student.last_name ?? ""}`.trim()}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h2 className="font-semibold">
        {student.first_name} {student.last_name}
      </h2>
      <div className="grid gap-2 sm:grid-cols-3">
        <TextField
          label={t("portal.preferredName")}
          value={form.preferred_name ?? ""}
          onChange={(e) => setForm({ ...form, preferred_name: e.target.value })}
        />
        <TextField
          label={t("portal.school")}
          value={form.school ?? ""}
          onChange={(e) => setForm({ ...form, school: e.target.value })}
        />
        <TextField
          label={t("portal.yearGroup")}
          value={form.year_group ?? ""}
          onChange={(e) => setForm({ ...form, year_group: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <label htmlFor={needsId} className="text-sm font-medium">
          {t("portal.learningNeeds")}
        </label>
        <textarea
          id={needsId}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          value={form.learning_needs ?? ""}
          onChange={(e) => setForm({ ...form, learning_needs: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">{t("portal.learningNeedsHelp")}</p>
      </div>
      {save.isSuccess ? <Alert tone="success">{t("portal.saved")}</Alert> : null}
      <Button type="submit" disabled={save.isPending}>
        {t("portal.save")}
      </Button>
    </form>
  );
}

/** The household's details, what they receive, and students' details (FR-15-8). */
export function ProfilePage() {
  const { t } = useTranslation();
  const profile = useQuery({
    queryKey: ["portal", "profile"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/profile")),
  });
  if (profile.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("portal.nav.profile")}</h1>
      {profile.data?.contacts.map((c) => (
        <ContactForm key={c.id} contact={c} />
      ))}
      {profile.data?.students.map((s) => (
        <StudentForm key={s.id} student={s} />
      ))}
    </div>
  );
}
