import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, FactList, Panel, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { GENDERS, splitTags } from "../matching/needs";

type Tutor = components["schemas"]["Tutor"];
type Student = components["schemas"]["Student"];
type Gender = "" | components["schemas"]["TutorGenderEnum"];

/** The profile as ruled facts; an empty value reads "None recorded". */
function Facts({ items }: { items: [string, string][] }) {
  const { t } = useTranslation();
  return <FactList items={items} empty={t("g5c.profile.none")} />;
}

/** Edit opens the form in place of the facts. */
function EditButton({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation();
  return (
    <Button size="sm" variant="secondary" onClick={onClick}>
      {t("g5c.profile.edit")}
    </Button>
  );
}

/** Whether the organisation lets families state a tutor gender preference (gap G5c). */
function useGenderPreferences(): boolean {
  const canSearch = usePermission("matching.search");
  const settings = useQuery({
    queryKey: ["matching-weights"],
    queryFn: async () => unwrap(await api.GET("/api/v1/matching/settings")),
    enabled: canSearch,
  });
  return Boolean(settings.data?.gender_preference);
}

/** A tutor's matching profile (gap G5c, FR-19-1): SEN experience, exam boards and, for
 * staff who may see it, gender (used only for families' gender preferences). */
export function TutorMatchingCard({ tutor }: { tutor: Tutor }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("people.tutor.edit");
  const seesGender = "gender" in tutor;
  const [editing, setEditing] = useState(false);
  const [sen, setSen] = useState((tutor.sen_tags ?? []).join(", "));
  const [boards, setBoards] = useState((tutor.exam_boards ?? []).join(", "));
  const [gender, setGender] = useState<Gender>((tutor.gender ?? "") as Gender);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/tutors/{id}", {
          params: { path: { id: tutor.id } },
          body: {
            sen_tags: splitTags(sen),
            exam_boards: splitTags(boards),
            ...(seesGender ? { gender } : {}),
            invite: false,
          },
        }),
      ),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ["tutors"] });
    },
  });
  const genderLabel = (value?: string) => (value ? t(`g5c.genders.${value}`) : "");
  return (
    <Panel
      title={t("g5c.profile.title")}
      flush
      aside={canEdit && !editing ? <EditButton onClick={() => setEditing(true)} /> : null}
    >
      {editing ? (
        <form
          className="space-y-3 px-5 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <TextField
            label={t("g5c.profile.senExperience")}
            hint={t("g5c.needs.listHint")}
            value={sen}
            onChange={(e) => setSen(e.target.value)}
          />
          <TextField
            label={t("g5c.needs.examBoards")}
            hint={t("g5c.needs.listHint")}
            value={boards}
            onChange={(e) => setBoards(e.target.value)}
          />
          {seesGender ? (
            <SelectField
              label={t("g5c.profile.gender")}
              hint={t("g5c.profile.genderHint")}
              value={gender}
              onChange={(e) => setGender(e.target.value as Gender)}
              options={[
                { value: "", label: t("g5c.profile.notRecorded") },
                ...GENDERS.map((g) => ({ value: g, label: t(`g5c.genders.${g}`) })),
              ]}
            />
          ) : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={save.isPending}>
              {t("common.save")}
            </Button>
            <Button type="button" variant="secondary" onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </Button>
          </div>
          {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
        </form>
      ) : (
        <Facts
            items={[
              [t("g5c.profile.senExperience"), (tutor.sen_tags ?? []).join(", ")],
              [t("g5c.needs.examBoards"), (tutor.exam_boards ?? []).join(", ")],
              ...(seesGender
                ? ([[t("g5c.profile.gender"), genderLabel(tutor.gender)]] as [string, string][])
                : []),
            ]}
          />

      )}
    </Panel>
  );
}

/** A student's needs for matching (gap G5c, FR-19-1): exam boards and, for staff who may
 * see sensitive details, SEN tags and the family's tutor gender preference. */
export function StudentMatchingCard({ student }: { student: Student }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("people.student.edit");
  const sensitive = "sen_tags" in student;
  const preferences = useGenderPreferences();
  const [editing, setEditing] = useState(false);
  const boardsOf = (value: unknown) =>
    Array.isArray(value) ? value.filter((v) => typeof v === "string").join(", ") : "";
  const [boards, setBoards] = useState(boardsOf(student.exam_boards));
  const [sen, setSen] = useState((student.sen_tags ?? []).join(", "));
  const [gender, setGender] = useState<Gender>((student.tutor_gender_preference ?? "") as Gender);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/students/{id}", {
          params: { path: { id: student.id } },
          body: {
            exam_boards: splitTags(boards),
            ...(sensitive ? { sen_tags: splitTags(sen) } : {}),
            ...(sensitive && preferences ? { tutor_gender_preference: gender } : {}),
          },
        }),
      ),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ["students"] });
    },
  });
  const preference = student.tutor_gender_preference
    ? t(`g5c.genders.${student.tutor_gender_preference}`)
    : t("g5c.needs.noPreference");
  return (
    <Panel
      title={t("g5c.profile.studentTitle")}
      flush
      aside={canEdit && !editing ? <EditButton onClick={() => setEditing(true)} /> : null}
    >
      {editing ? (
        <form
          className="space-y-3 px-5 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <TextField
            label={t("g5c.needs.examBoards")}
            hint={t("g5c.needs.listHint")}
            value={boards}
            onChange={(e) => setBoards(e.target.value)}
          />
          {sensitive ? (
            <TextField
              label={t("g5c.needs.senTags")}
              hint={t("g5c.needs.listHint")}
              value={sen}
              onChange={(e) => setSen(e.target.value)}
            />
          ) : null}
          {sensitive && preferences ? (
            <SelectField
              label={t("g5c.needs.gender")}
              value={gender}
              onChange={(e) => setGender(e.target.value as Gender)}
              options={[
                { value: "", label: t("g5c.needs.noPreference") },
                ...GENDERS.map((g) => ({ value: g, label: t(`g5c.genders.${g}`) })),
              ]}
            />
          ) : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={save.isPending}>
              {t("common.save")}
            </Button>
            <Button type="button" variant="secondary" onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </Button>
          </div>
          {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
        </form>
      ) : (
        <Facts
            items={[
              [t("g5c.needs.examBoards"), boardsOf(student.exam_boards)],
              ...(sensitive
                ? ([[t("g5c.needs.senTags"), (student.sen_tags ?? []).join(", ")]] as [
                    string,
                    string,
                  ][])
                : []),
              ...(sensitive && preferences
                ? ([[t("g5c.needs.gender"), preference]] as [string, string][])
                : []),
            ]}
          />

      )}
    </Panel>
  );
}
