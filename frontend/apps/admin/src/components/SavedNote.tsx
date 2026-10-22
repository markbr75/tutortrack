import { useTranslation } from "@tutortrack/i18n";

/** "Saved." in success ink beside Save in a panel footer, announced politely. */
export function SavedNote({ show, text }: { show: boolean; text?: string }) {
  const { t } = useTranslation();
  return show ? (
    <p role="status" className="text-success">
      {text ?? t("common.saved")}
    </p>
  ) : null;
}
