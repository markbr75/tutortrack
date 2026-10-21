import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, RuledPanel, SelectField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, usePermission } from "../api";
import { AnnualEarningsLinks, FullBankDetails } from "../g3/PayrollExtras";
import { PayPhase3Fields } from "./PayPhase3";

const METHODS = ["manual", "bank_file", "stripe_connect", "wise", "external_payroll"] as const;

/** How the tutor is paid (FR-12-2); bank details stay masked. */
export function PayProfileCard({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canView = usePermission("payroll.view");
  const canManage = usePermission("payroll.profile.manage");
  const profile = useQuery({
    queryKey: ["pay-profile", tutorId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors/{id}/pay-profile", { params: { path: { id: tutorId } } }),
      ),
    enabled: canView,
  });
  const update = useMutation({
    mutationFn: async (method: (typeof METHODS)[number]) =>
      unwrap(
        await api.PATCH("/api/v1/tutors/{id}/pay-profile", {
          params: { path: { id: tutorId } },
          body: { method },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["pay-profile", tutorId], data),
  });
  if (!canView || !profile.data) return null;
  const p = profile.data;
  return (
    <RuledPanel flush titleId="pay-profile" title={t("payroll.payProfile")}>
      <div className="space-y-3 px-5 py-4">
        <div className="max-w-xs">
          <SelectField
            label={t("payroll.method")}
            disabled={!canManage}
            value={p.method}
            onChange={(e) => update.mutate(e.target.value as (typeof METHODS)[number])}
            options={METHODS.map((m) => ({
              value: m,
              label: m === "wise" ? t("payrollPhase3.methodWise") : t(`payroll.methods.${m}`),
            }))}
          />
        </div>
        <p className="text-sm tabular-nums">
          {p.bank_hint ? t("pay.bankOnFile", { hint: p.bank_hint }) : t("pay.noBank")}
          {p.self_billing_agreed_at ? ` · ${t("payroll.selfBillingAgreed")}` : ""}
          {p.vat_registered ? ` · ${t("payroll.vatRegistered", { number: p.vat_number })}` : ""}
        </p>
        {update.error ? <Alert tone="danger">{update.error.message}</Alert> : null}
        {p.method === "stripe_connect" && !p.stripe_payouts_enabled ? (
          <p className="text-sm text-muted-foreground">{t("payroll.stripePending")}</p>
        ) : null}
        {p.method === "wise" && !p.wise_ready ? (
          <p className="text-sm text-muted-foreground">{t("payrollPhase3.wiseNeedsBank")}</p>
        ) : null}
        <FullBankDetails tutorId={tutorId} />
        <AnnualEarningsLinks tutorId={tutorId} />
      </div>
      <div className="border-t border-border">
        <PayPhase3Fields tutorId={tutorId} />
      </div>
    </RuledPanel>
  );
}
