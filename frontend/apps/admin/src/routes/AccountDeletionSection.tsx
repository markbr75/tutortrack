import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, fieldErrors } from "../api";

/** G6 (FR-03-9): delete your whole TutorTrack account, in every organisation. Shows what
 *  happens in each one first; last owners must hand over or close their organisation. */
export function AccountDeletionSection() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmEmail, setConfirmEmail] = useState("");
  const [reason, setReason] = useState("");
  const preview = useQuery({
    queryKey: ["me-account-deletion"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/account-deletion")),
    enabled: open,
  });
  const remove = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/me/account-deletion", {
          body: { password, confirm_email: confirmEmail, reason },
        }),
      ),
    onSuccess: () => window.location.assign("/login?deleted=1"),
  });
  const errors = fieldErrors(remove.error);
  const blockers = preview.data?.blockers ?? [];

  function submit(event: FormEvent) {
    event.preventDefault();
    remove.mutate();
  }

  return (
    <section
      aria-labelledby="delete-account-h"
      className="mt-8 max-w-2xl rounded-md border border-danger/40 p-4 md:p-6"
    >
      <h2 id="delete-account-h" className="text-lg font-semibold">
        {t("accountDeletion.title")}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">{t("accountDeletion.intro")}</p>
      {!open ? (
        <Button className="mt-3" variant="danger" onClick={() => setOpen(true)}>
          {t("accountDeletion.start")}
        </Button>
      ) : null}
      {open && preview.data ? (
        <div className="mt-4 space-y-3 text-sm">
          {preview.data.organisations.length ? (
            <ul className="list-disc space-y-1 pl-5">
              {preview.data.organisations.map((org) => (
                <li key={org.organisation_id}>
                  {t(`accountDeletion.outcome.${org.outcome}`, { organisation: org.name })}
                </li>
              ))}
            </ul>
          ) : null}
          {blockers.length ? (
            <Alert tone="danger">
              <p>{t("accountDeletion.blocked")}</p>
              <ul className="list-disc pl-5">
                {blockers.map((b) => (
                  <li key={`${b.organisation_id}-${b.reason}`}>
                    {t(`accountDeletion.blockers.${b.reason}`, {
                      organisation: b.organisation_name,
                    })}
                  </li>
                ))}
              </ul>
            </Alert>
          ) : (
            <form onSubmit={submit} className="space-y-3" noValidate>
              {preview.data.needs_password ? (
                <TextField
                  label={t("accountDeletion.password")}
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  error={errors.password}
                  required
                />
              ) : (
                <TextField
                  label={t("accountDeletion.confirmEmail")}
                  type="email"
                  value={confirmEmail}
                  onChange={(e) => setConfirmEmail(e.target.value)}
                  error={errors.confirm_email}
                  required
                />
              )}
              <TextField
                label={t("accountDeletion.reason")}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <p className="font-medium">{t("accountDeletion.final")}</p>
              {remove.isError && !Object.keys(errors).length ? (
                <Alert tone="danger">{remove.error.message}</Alert>
              ) : null}
              <div className="flex gap-2">
                <Button type="submit" variant="danger" loading={remove.isPending}>
                  {t("accountDeletion.confirm")}
                </Button>
                <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
                  {t("accountDeletion.cancel")}
                </Button>
              </div>
            </form>
          )}
        </div>
      ) : null}
    </section>
  );
}
