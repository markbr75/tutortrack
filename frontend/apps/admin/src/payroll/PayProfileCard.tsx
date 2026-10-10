import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, usePermission } from "../api";

const METHODS = ["manual", "bank_file", "stripe_connect", "external_payroll"] as const;

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
    <section className="rounded-lg border border-border p-4" aria-labelledby="pay-profile">
      <h2 id="pay-profile" className="mb-2 font-semibold">
        {t("payroll.payProfile")}
      </h2>
      <label className="flex items-center gap-2 text-sm">
        <span>{t("payroll.method")}</span>
        <select
          disabled={!canManage}
          className="h-9 rounded-md border border-border bg-background px-2"
          value={p.method}
          onChange={(e) => update.mutate(e.target.value as (typeof METHODS)[number])}
        >
          {METHODS.map((m) => (
            <option key={m} value={m}>
              {t(`payroll.methods.${m}`)}
            </option>
          ))}
        </select>
      </label>
      <p className="mt-2 text-sm">
        {p.bank_hint ? t("pay.bankOnFile", { hint: p.bank_hint }) : t("pay.noBank")}
        {p.self_billing_agreed_at ? ` · ${t("payroll.selfBillingAgreed")}` : ""}
        {p.vat_registered ? ` · ${t("payroll.vatRegistered", { number: p.vat_number })}` : ""}
      </p>
      {update.error ? <Alert tone="danger">{update.error.message}</Alert> : null}
      {p.method === "stripe_connect" && !p.stripe_payouts_enabled ? (
        <p className="mt-2 text-sm text-muted-foreground">{t("payroll.stripePending")}</p>
      ) : null}
    </section>
  );
}
