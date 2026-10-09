import { useTranslation } from "@tutortrack/i18n";
import { Alert } from "@tutortrack/ui";

import { fieldErrors } from "../api";
import { conflictsOf } from "./types";

export function ErrorList({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const conflicts = conflictsOf(error);
  const messages = conflicts.length
    ? conflicts.map((c) => c.message)
    : Object.values(fieldErrors(error));
  return (
    <Alert
      tone="danger"
      title={conflicts.length ? t("calendar.conflict") : undefined}
      className="mt-2"
    >
      {messages.length ? messages.join(" ") : t("errors.generic")}
    </Alert>
  );
}
