import { useTranslation } from "@tutortrack/i18n";

/** Why a job needs attention (FR-07-6, gap G3), as the API names the reasons. */
export const ATTENTION_REASONS = [
  "seeking_tutor",
  "open_offer",
  "no_upcoming_lessons",
  "low_balance",
  "overdue_reports",
] as const;
export type AttentionReason = (typeof ATTENTION_REASONS)[number];

/** The reasons in words, one per line; nothing when the job is fine. */
export function AttentionReasons({ reasons }: { reasons: readonly string[] | undefined }) {
  const { t } = useTranslation();
  if (!reasons?.length) return null;
  return (
    <ul className="text-sm" aria-label={t("g3.attention.column")}>
      {reasons.map((r) => (
        <li key={r} className="whitespace-nowrap">
          {t(`g3.attention.reasons.${r}`)}
        </li>
      ))}
    </ul>
  );
}
