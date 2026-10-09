import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useMutation } from "@tanstack/react-query";

import { api } from "../api";

/** Invite a parent (contact) to the family portal (E15-T01). */
export function InviteButton({ contactId, name }: { contactId: string; name: string }) {
  const { t } = useTranslation();
  const invite = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/{kind}/{record_id}/portal-invite", {
          params: { path: { kind: "contacts", record_id: contactId } },
          body: { email: "" },
        }),
      ),
  });
  if (invite.isSuccess) {
    return <span className="text-xs text-muted-foreground">{t("announcements.invited")}</span>;
  }
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => invite.mutate()} disabled={invite.isPending}>
        {t("announcements.invite")}
        <span className="sr-only"> {name}</span>
      </Button>
      {invite.error ? (
        <span role="alert" className="text-xs text-danger">
          {invite.error.message}
        </span>
      ) : null}
    </>
  );
}
