import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { SelectField, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePortalMe } from "../api";
import { PortalHeader } from "../layout/PortalPage";
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
    <div>
      <PortalHeader
        title={t("portal.nav.schedule")}
        actions={
          students.length > 1 ? (
            <SelectField
              size="sm"
              hideLabel
              label={t("portal.student")}
              value={student}
              onChange={(e) => setStudent(e.target.value)}
              options={[
                { value: "", label: t("designS10.allStudents") },
                ...students.map((s) => ({ value: s.id, label: s.name })),
              ]}
            />
          ) : null
        }
      />
      {lessons.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : lessons.data?.length ? (
        <ul className="space-y-3">
          {lessons.data.map((lesson) => (
            <li key={lesson.id}>
              <LessonCard lesson={lesson} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          {t("portal.noLessons")}{" "}
          {me.data?.features.booking ? (
            <Link to="/book" className="font-medium text-link underline-offset-2 hover:underline">
              {t("portalBooking.title")}
            </Link>
          ) : null}
        </p>
      )}
    </div>
  );
}
