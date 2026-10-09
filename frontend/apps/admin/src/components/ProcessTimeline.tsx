import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { useQuery } from "@tanstack/react-query";

import { api, usePermission } from "../api";

/**
 * Durable processes (Temporal workflows) linked to a record: what is running, which step it
 * is on, and how earlier ones ended (E32 §6). Drop it on any record page:
 * `<ProcessTimeline subjectType="invoice" subjectId={invoice.id} />`.
 */
export function ProcessTimeline({ subjectType, subjectId }: { subjectType: string; subjectId: string }) {
  const { t, i18n } = useTranslation();
  const allowed = usePermission("processes.view");
  const processes = useQuery({
    queryKey: ["processes", subjectType, subjectId],
    enabled: allowed,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/processes", {
          params: { query: { subject_type: subjectType, subject_id: subjectId } },
        }),
      ),
  });
  const rows = processes.data?.results ?? [];
  if (!allowed || rows.length === 0) return null;
  return (
    <section aria-labelledby="process-timeline" className="mt-8 max-w-2xl">
      <h2 id="process-timeline" className="text-lg font-medium">
        {t("processes.title")}
      </h2>
      <ol className="mt-2 border-l border-border pl-4">
        {rows.map((p) => (
          <li key={p.id} className="relative pb-4">
            <span
              aria-hidden="true"
              className={`absolute top-1.5 -left-[1.3rem] size-2.5 rounded-full ${
                p.status === "running" ? "bg-brand" : p.status === "completed" ? "bg-success" : "bg-danger"
              }`}
            />
            <p className="text-sm font-medium">{t(`processes.names.${p.process}`, p.process)}</p>
            <p className="text-sm text-muted-foreground">
              {t(`processes.status.${p.status}`)}
              {p.current_step ? ` · ${t(`processes.steps.${p.current_step}`, p.current_step)}` : ""}
              {" · "}
              {formatDateTime(p.started_at, i18n.language)}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
