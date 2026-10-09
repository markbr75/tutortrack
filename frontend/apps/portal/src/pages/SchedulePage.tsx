import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { SelectField, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePortalMe } from "../api";
import { LessonCard } from "./LessonCard";

/** Lessons for every student in the household, filterable by student (FR-15-3). */
export function SchedulePage() {
  const { t } = useTranslation();
  const me = usePortalMe();
  const [student, setStudent] = useState("");
  const lessons = useQuery({
    queryKey: ["portal", "schedule", student],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/portal/schedule", {
          params: { query: { student: student || undefined } },
        }),
      ),
  });
  const students = me.data?.students ?? [];
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("portal.nav.schedule")}</h1>
      {students.length > 1 ? (
        <SelectField
          label={t("portal.student")}
          value={student}
          onChange={(e) => setStudent(e.target.value)}
          options={[
            { value: "", label: t("portal.everyone") },
            ...students.map((s) => ({ value: s.id, label: s.name })),
          ]}
        />
      ) : null}
      {lessons.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : lessons.data?.length ? (
        lessons.data.map((lesson) => <LessonCard key={lesson.id} lesson={lesson} />)
      ) : (
        <p className="text-sm text-muted-foreground">{t("portal.noLessons")}</p>
      )}
    </div>
  );
}
