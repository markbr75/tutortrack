import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api, fieldErrors } from "../api";

interface StudentDraft {
  first_name: string;
  year_group: string;
  subject: string;
}

const EMPTY_STUDENT: StudentDraft = { first_name: "", year_group: "", subject: "" };

/** One-screen "add a family": contact, students and billing address (FR-05-1). */
export function QuickAddFamilyPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [contact, setContact] = useState({ first_name: "", last_name: "", email: "", phone: "" });
  const [students, setStudents] = useState<StudentDraft[]>([{ ...EMPTY_STUDENT }]);
  const [address, setAddress] = useState({ line1: "", city: "", postcode: "" });

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/clients/quick-add", {
          body: {
            contact: { ...contact, relationship: "parent" },
            students: students
              .filter((s) => s.first_name.trim())
              .map((s) => ({
                first_name: s.first_name,
                year_group: s.year_group,
                subjects: s.subject ? [{ subject: s.subject }] : [],
              })),
            ...(address.line1 || address.postcode ? { billing_address: address } : {}),
          },
        }),
      ),
    onSuccess: (client) => {
      void queryClient.invalidateQueries({ queryKey: ["clients"] });
      void navigate({ to: "/clients/$clientId", params: { clientId: client.id } });
    },
  });
  const errors = fieldErrors(save.error);
  const contactErrors = (errors.contact ?? "") as string;

  const setStudent = (index: number, patch: Partial<StudentDraft>) =>
    setStudents((list) => list.map((s, i) => (i === index ? { ...s, ...patch } : s)));

  return (
    <section className="max-w-3xl">
      <p className="mb-2 text-sm">
        <Link to="/clients" className="underline-offset-2 hover:underline">
          {t("people.clients")}
        </Link>
      </p>
      <h1 className="mb-6 text-2xl font-semibold">{t("people.quickAdd.title")}</h1>
      {save.isError ? (
        <Alert tone="danger" title={t("people.quickAdd.failed")} className="mb-4">
          {contactErrors || null}
        </Alert>
      ) : null}
      <form
        className="space-y-8"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <fieldset className="grid gap-3 sm:grid-cols-2">
          <legend className="mb-2 font-semibold">{t("people.quickAdd.parent")}</legend>
          <TextField
            label={t("people.firstName")}
            required
            autoComplete="off"
            value={contact.first_name}
            onChange={(e) => setContact((c) => ({ ...c, first_name: e.target.value }))}
          />
          <TextField
            label={t("people.lastName")}
            autoComplete="off"
            value={contact.last_name}
            onChange={(e) => setContact((c) => ({ ...c, last_name: e.target.value }))}
          />
          <TextField
            label={t("people.email")}
            type="email"
            autoComplete="off"
            value={contact.email}
            onChange={(e) => setContact((c) => ({ ...c, email: e.target.value }))}
          />
          <TextField
            label={t("people.phone")}
            type="tel"
            autoComplete="off"
            value={contact.phone}
            onChange={(e) => setContact((c) => ({ ...c, phone: e.target.value }))}
          />
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="mb-2 font-semibold">{t("people.students")}</legend>
          {students.map((student, index) => (
            <div key={index} className="grid gap-3 sm:grid-cols-[1fr_10rem_1fr_auto] sm:items-end">
              <TextField
                label={t("people.quickAdd.studentName", { n: index + 1 })}
                value={student.first_name}
                onChange={(e) => setStudent(index, { first_name: e.target.value })}
              />
              <TextField
                label={t("people.yearGroup")}
                value={student.year_group}
                onChange={(e) => setStudent(index, { year_group: e.target.value })}
              />
              <TextField
                label={t("people.quickAdd.subject")}
                value={student.subject}
                onChange={(e) => setStudent(index, { subject: e.target.value })}
              />
              {students.length > 1 ? (
                <Button
                  type="button"
                  variant="secondary"
                  aria-label={t("people.quickAdd.removeStudent", { n: index + 1 })}
                  onClick={() => setStudents((list) => list.filter((_, i) => i !== index))}
                >
                  {t("people.quickAdd.remove")}
                </Button>
              ) : null}
            </div>
          ))}
          <Button
            type="button"
            variant="secondary"
            onClick={() => setStudents((list) => [...list, { ...EMPTY_STUDENT }])}
          >
            {t("people.quickAdd.addStudent")}
          </Button>
        </fieldset>

        <fieldset className="grid gap-3 sm:grid-cols-3">
          <legend className="mb-2 font-semibold">{t("people.billingAddress")}</legend>
          <TextField
            label={t("people.address.line1")}
            value={address.line1}
            onChange={(e) => setAddress((a) => ({ ...a, line1: e.target.value }))}
          />
          <TextField
            label={t("people.address.city")}
            value={address.city}
            onChange={(e) => setAddress((a) => ({ ...a, city: e.target.value }))}
          />
          <TextField
            label={t("people.address.postcode")}
            value={address.postcode}
            onChange={(e) => setAddress((a) => ({ ...a, postcode: e.target.value }))}
          />
        </fieldset>

        <Button type="submit" disabled={save.isPending}>
          {t("people.quickAdd.save")}
        </Button>
      </form>
    </section>
  );
}
