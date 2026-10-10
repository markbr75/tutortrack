import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

/** Incident and maintenance notices posted from the platform console (E30 FR-30-3). */
export function StatusBanner() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ["platform-status"],
    queryFn: async () => unwrap(await api.GET("/api/v1/status")),
    refetchInterval: 120_000,
    retry: false,
  });
  if (!data?.notices.length) return null;
  return (
    <div role="status" className="space-y-1">
      {data.notices.map((notice) => (
        <p
          key={notice.id}
          className={
            notice.severity === "info"
              ? "bg-muted px-4 py-2 text-sm"
              : "bg-amber-100 px-4 py-2 text-sm text-amber-950"
          }
        >
          <span className="font-medium">{t(`status.${notice.severity}`)}:</span> {notice.message}
          {data.status_page_url ? (
            <>
              {" "}
              <a className="underline" href={data.status_page_url}>
                {t("status.more")}
              </a>
            </>
          ) : null}
        </p>
      ))}
    </div>
  );
}
