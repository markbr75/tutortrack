import { type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";

import { useSyncStatuses } from "./useSyncStatuses";

export type SyncRecord = components["schemas"]["ExternalRecordLink"];

/** "In Xero", "Sync error"... in words (errors in danger), with the reason as accessible text. */
export function SyncBadge({ record }: { record?: SyncRecord }) {
  const { t } = useTranslation();
  if (!record) return null;
  const provider = t(`accounting.providers.${record.provider}`);
  const label = t(`accounting.badge.${record.status}`, { provider });
  return (
    <span
      className={
        record.status === "error" ? "font-medium text-danger" : "text-muted-foreground"
      }
      title={record.error || undefined}
    >
      {label}
      {record.status === "error" && record.error ? (
        <span className="sr-only">: {record.error}</span>
      ) : null}
    </span>
  );
}

/** The badge for one record (invoice page). */
export function RecordSyncBadge({
  objectType,
  id,
}: {
  objectType: "invoice" | "payment";
  id: string;
}) {
  const statuses = useSyncStatuses(objectType, [id]);
  return <SyncBadge record={statuses.data?.[id]} />;
}
