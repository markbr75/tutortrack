import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { NamePlate, Panel, PanelRow, PanelRows } from "@tutortrack/ui";
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
  const rows = jobs.data?.results ?? [];
  return (
    <Panel title={t("jobs.title")} flush>
      {jobs.isPending ? (
        <div aria-hidden="true" className="px-5 py-4">
          <div className="h-8 animate-pulse rounded bg-muted" />
        </div>
      ) : rows.length ? (
        <PanelRows>
          {rows.map((job) => (
            <PanelRow key={job.id}>
              <NamePlate
                name={
                  <Link
                    className="underline-offset-2 hover:underline"
                    to="/jobs/$jobId"
                    params={{ jobId: job.id }}
                  >
                    {job.name}
                  </Link>
                }
                context={t(`jobs.status.${job.status}`)}
              />
            </PanelRow>
          ))}
        </PanelRows>
      ) : (
        <p className="px-5 py-4 text-sm text-muted-foreground">{t("jobs.none")}</p>
      )}
      {canCreate ? (
        <div className="border-t border-rule px-5 py-4">
          <QuickSetup studentId={studentId} />
        </div>
      ) : null}
    </Panel>
  );
}
