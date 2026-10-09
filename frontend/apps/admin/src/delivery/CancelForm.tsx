import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type CancelledBy = components["schemas"]["CancelledByEnum"];
type CancelResult = components["schemas"]["CancelResult"];
const WHO: CancelledBy[] = ["client", "student", "tutor", "admin"];

/** Cancel under the cancellation policy (FR-09-3): who cancelled, the policy outcome
 * previewed before confirming, an optional (permissioned) override and the series scope. */
export function CancelForm({
  lessonId,
  inSeries,
  onDone,
}: {
  lessonId: string;
  inSeries: boolean;
  onDone: (result: CancelResult) => void;
}) {
  const { t } = useTranslation();
  const canOverride = usePermission("delivery.cancel.override_policy");
  const [who, setWho] = useState<CancelledBy>("client");
  const [reason, setReason] = useState("");
  const [following, setFollowing] = useState(false);
  const [notify, setNotify] = useState(true);
  const [override, setOverride] = useState<null | { charge: string; pay: string; why: string }>(
    null,
  );

  const body = () => ({
    cancelled_by: who,
    reason,
    notify,
    scope: following ? ("following" as const) : ("this" as const),
    override: override
      ? { charge_percent: override.charge, pay_percent: override.pay, reason: override.why }
      : null,
  });
  const preview = useQuery({
    queryKey: ["lesson", lessonId, "cancel-preview", who],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/lessons/{id}/cancel", {
          params: { path: { id: lessonId }, query: { preview: true } },
          body: { cancelled_by: who, reason: "", notify: false, scope: "this" },
        }),
      ),
  });
  const confirm = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/lessons/{id}/cancel", {
          params: { path: { id: lessonId } },
          body: body(),
        }),
      ),
    onSuccess: onDone,
  });
  const outcome = preview.data?.outcome;

  return (
    <form
      className="mt-4 space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        confirm.mutate();
      }}
    >
      <SelectField
        label={t("delivery.cancel.who")}
        value={who}
        onChange={(e) => setWho(e.target.value as CancelledBy)}
        options={WHO.map((w) => ({ value: w, label: t(`delivery.cancel.by.${w}`) }))}
      />
      <TextField
        label={t("calendar.reason")}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div aria-live="polite">
        {outcome ? (
          <Alert tone={outcome.kind === "late" ? "warning" : "info"}>{outcome.message}</Alert>
        ) : (
          <p className="text-sm text-muted-foreground">{t("delivery.cancel.checking")}</p>
        )}
      </div>
      {canOverride ? (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={override !== null}
            onChange={(e) =>
              setOverride(
                e.target.checked
                  ? {
                      charge: outcome?.charge_percent ?? "0",
                      pay: outcome?.pay_percent ?? "0",
                      why: "",
                    }
                  : null,
              )
            }
          />
          {t("delivery.cancel.override")}
        </label>
      ) : null}
      {override ? (
        <div className="grid grid-cols-2 gap-2">
          <TextField
            type="number"
            min={0}
            max={100}
            label={t("delivery.cancel.chargePercent")}
            value={override.charge}
            onChange={(e) => setOverride({ ...override, charge: e.target.value })}
          />
          <TextField
            type="number"
            min={0}
            max={100}
            label={t("delivery.cancel.payPercent")}
            value={override.pay}
            onChange={(e) => setOverride({ ...override, pay: e.target.value })}
          />
          <div className="col-span-2">
            <TextField
              label={t("delivery.cancel.overrideReason")}
              value={override.why}
              onChange={(e) => setOverride({ ...override, why: e.target.value })}
            />
          </div>
        </div>
      ) : null}
      {inSeries ? (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={following}
            onChange={(e) => setFollowing(e.target.checked)}
          />
          {t("delivery.cancel.following")}
        </label>
      ) : null}
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={notify}
          onChange={(e) => setNotify(e.target.checked)}
        />
        {t("delivery.cancel.notify")}
      </label>
      <ErrorList error={confirm.error} />
      <Button type="submit" variant="danger" disabled={confirm.isPending}>
        {t("calendar.confirmCancel")}
      </Button>
    </form>
  );
}
