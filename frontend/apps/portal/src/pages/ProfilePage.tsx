import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Button,
  CheckboxField,
  PanelFooter,
  RuledPanel,
  Spinner,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { DigestPreferences } from "../digests/DigestPreferences";
import { PortalHeader, SavedNote } from "../layout/PortalPage";

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
      aria-label={t("portal.yourDetails")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <RuledPanel title={t("portal.yourDetails")} description={form.email} flush>
        <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
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
        <div className="border-t border-rule px-5 py-4">
          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-medium">{t("portal.whatToReceive")}</legend>
            {FLAGS.map((flag) => (
              <CheckboxField
                key={flag}
                label={t(`portal.flags.${flag}`)}
                checked={Boolean(form[flag])}
                onChange={(e) => setForm({ ...form, [flag]: e.target.checked })}
              />
            ))}
          </fieldset>
        </div>
        <PanelFooter>
          <Button type="submit" disabled={save.isPending}>
            {t("portal.save")}
          </Button>
          <SavedNote show={save.isSuccess} />
        </PanelFooter>
      </RuledPanel>
    </form>
  );
}

function StudentForm({ student }: { student: Student }) {
  const { t } = useTranslation();
  const [form, setForm] = useState(student);
  const name = `${student.first_name} ${student.last_name ?? ""}`.trim();
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
      aria-label={name}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <RuledPanel title={name} flush>
        <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-3">
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
          <div className="sm:col-span-3">
            <TextAreaField
              label={t("portal.learningNeeds")}
              hint={t("portal.learningNeedsHelp")}
              value={form.learning_needs ?? ""}
              onChange={(e) => setForm({ ...form, learning_needs: e.target.value })}
            />
          </div>
        </div>
        <PanelFooter>
          <Button type="submit" disabled={save.isPending}>
            {t("portal.save")}
          </Button>
          <SavedNote show={save.isSuccess} />
        </PanelFooter>
      </RuledPanel>
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
  if (profile.isPending) return <Spinner label={t("grid.loading")} />;
  return (
    <div>
      <PortalHeader title={t("portal.nav.profile")} />
      <div className="space-y-6">
        {profile.data?.contacts.map((c) => (
          <ContactForm key={c.id} contact={c} />
        ))}
        {profile.data?.students.map((s) => (
          <StudentForm key={s.id} student={s} />
        ))}
        <DigestPreferences />
      </div>
    </div>
  );
}
