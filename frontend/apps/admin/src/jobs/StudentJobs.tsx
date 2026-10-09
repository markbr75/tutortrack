import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api, usePermission } from "../api";
import { QuickSetup } from "./QuickSetup";

/** The student's jobs, plus "Set up lessons" (E07 FR-07-2). */
export function StudentJobs({ studentId }: { studentId: string }) {
  const { t } = useTranslation();
  const canView = usePermission("jobs.job.view");
  const canCreate = usePermission("jobs.job.create");
  const jobs = useQuery({
    queryKey: ["jobs", { student: studentId }],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/jobs", { params: { query: { student: studentId } } })),
    enabled: canView,
  });
  if (!canView) return null;
  return (
    <section className="rounded-lg border border-border p-4">
      <h2 className="mb-3 font-semibold">{t("jobs.title")}</h2>
      <ul className="mb-3 space-y-1">
        {(jobs.data?.results ?? []).map((job) => (
          <li key={job.id}>
            <Link
              className="font-medium underline-offset-2 hover:underline"
              to="/jobs/$jobId"
              params={{ jobId: job.id }}
            >
              {job.name}
            </Link>{" "}
            <span className="text-sm text-muted-foreground">{t(`jobs.status.${job.status}`)}</span>
          </li>
        ))}
      </ul>
      {jobs.data && jobs.data.results.length === 0 ? (
        <p className="mb-3 text-sm text-muted-foreground">{t("jobs.none")}</p>
      ) : null}
      {canCreate ? <QuickSetup studentId={studentId} /> : null}
    </section>
  );
}
