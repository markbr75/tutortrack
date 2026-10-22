import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Panel, PanelRow, PanelRows } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";

import { api, usePermission } from "../api";

/**
 * Durable processes (Temporal workflows) linked to a record: what is running, which step it
 * is on, and how earlier ones ended (E32 §6). Drop it on any record page:
 * `<ProcessTimeline subjectType="invoice" subjectId={invoice.id} />`.
 */
export function ProcessTimeline({
  subjectType,
  subjectId,
}: {
  subjectType: string;
  subjectId: string;
}) {
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
    <Panel title={t("processes.title")} flush>
      <PanelRows>
        {rows.map((p) => (
          <PanelRow key={p.id}>
            <p className="font-medium">{t(`processes.names.${p.process}`, p.process)}</p>
            <p className="text-xs text-muted-foreground">
              <span className={p.status === "failed" ? "font-semibold text-danger" : undefined}>
                {t(`processes.status.${p.status}`)}
                {p.current_step
                  ? ` · ${t(`processes.steps.${p.current_step}`, p.current_step)}`
                  : ""}
              </span>
              {" · "}
              <time dateTime={p.started_at} className="tabular-nums">
                {formatDateTime(p.started_at, i18n.language)}
              </time>
            </p>
          </PanelRow>
        ))}
      </PanelRows>
    </Panel>
  );
}
