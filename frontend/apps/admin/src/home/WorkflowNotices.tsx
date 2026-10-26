import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api, usePermission } from "../api";

/** Built-in workflows that are switched off (and what happens instead) or have a newer
 * default (E33 FR-33-5). */
export function WorkflowNotices() {
  const { t } = useTranslation();
  const canView = usePermission("automation.view");
  const query = useQuery({
    queryKey: ["workflow-notices"],
    queryFn: async () => unwrap(await api.GET("/api/v1/workflows/notices")),
    enabled: canView,
  });
  const notices = query.data ?? [];
  if (!canView || notices.length === 0) return null;
  return (
    <Alert tone="warning" title={t("home.workflows")}>
      <ul className="mt-1 space-y-1">
        {notices.map((n) => (
          <li key={n.id}>
            {n.notice === "off"
              ? t("home.workflowOff", { name: n.name })
              : t("home.workflowUpdate", { name: n.name })}{" "}
            {n.message}{" "}
            <Link
              to="/workflows/$id"
              params={{ id: n.id }}
              className="font-medium underline underline-offset-2"
              aria-label={t("home.openWorkflow", { name: n.name })}
            >
              {t("home.openWorkflowShort")}
            </Link>
          </li>
        ))}
      </ul>
    </Alert>
  );
}
