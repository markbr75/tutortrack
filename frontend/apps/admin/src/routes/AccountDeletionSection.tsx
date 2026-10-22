import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, PanelFooter, RuledPanel, Spinner, TextField } from "@tutortrack/ui";
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
    <RuledPanel
      flush
      titleId="delete-account-h"
      title={t("accountDeletion.title")}
      description={t("accountDeletion.intro")}
      footer={
        !open ? (
          <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
            {t("accountDeletion.start")}
          </Button>
        ) : null
      }
    >
      {open && !preview.data ? (
        <div className="px-5 py-4">
          <Spinner label={t("grid.loading")} />
        </div>
      ) : null}
      {open && preview.data ? (
        <div className="text-sm">
          {preview.data.organisations.length ? (
            <ul className="divide-y divide-rule border-b border-rule">
              {preview.data.organisations.map((org) => (
                <li key={org.organisation_id} className="px-5 py-2.5">
                  {t(`accountDeletion.outcome.${org.outcome}`, { organisation: org.name })}
                </li>
              ))}
            </ul>
          ) : null}
          {blockers.length ? (
            <div className="px-5 py-4">
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
            </div>
          ) : (
            <form onSubmit={submit} noValidate aria-labelledby="delete-account-h">
              <div className="grid gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
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
                <p className="font-medium sm:col-span-2">{t("accountDeletion.final")}</p>
                {remove.isError && !Object.keys(errors).length ? (
                  <Alert tone="danger" className="sm:col-span-2">
                    {remove.error.message}
                  </Alert>
                ) : null}
              </div>
              <PanelFooter>
                <Button type="submit" variant="danger" loading={remove.isPending}>
                  {t("accountDeletion.confirm")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  className="text-muted-foreground"
                  onClick={() => setOpen(false)}
                >
                  {t("accountDeletion.cancel")}
                </Button>
              </PanelFooter>
            </form>
          )}
        </div>
      ) : null}
    </RuledPanel>
  );
}
