import { type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";

import { useSyncStatuses } from "./useSyncStatuses";

export type SyncRecord = components["schemas"]["ExternalRecordLink"];

const TONES: Record<string, string> = {
  synced: "bg-success/15",
  error: "bg-danger/15 text-danger",
  pending: "bg-amber-500/15",
  skipped: "bg-muted",
};

/** "In Xero", "Sync error"... with the reason as accessible text. */
export function SyncBadge({ record }: { record?: SyncRecord }) {
  const { t } = useTranslation();
  if (!record) return null;
  const provider = t(`accounting.providers.${record.provider}`);
  const label = t(`accounting.badge.${record.status}`, { provider });
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${TONES[record.status] ?? "bg-muted"}`}
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
