import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { ConnectProviders } from "../integrations/IntegrationsPage";
import { PayrollNav } from "./PayrollPages";

const TIN_TYPES = ["ssn", "itin", "ein"] as const;

/** E12-T12: commission pay (FR-12-10) and the tutor's US taxpayer id (1099-NEC). */
export function PayPhase3Fields({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("payroll.profile.manage");
  const profile = useQuery({
    queryKey: ["pay-profile", tutorId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors/{id}/pay-profile", { params: { path: { id: tutorId } } }),
      ),
  });
  const [basis, setBasis] = useState<"rate" | "commission" | null>(null);
  const [percent, setPercent] = useState<string | null>(null);
  const [tinType, setTinType] = useState<(typeof TIN_TYPES)[number]>("ssn");
  const [tin, setTin] = useState("");
  const saveBasis = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/tutors/{id}/pay-profile", {
          params: { path: { id: tutorId } },
          body: {
            pay_basis: basis ?? profile.data?.pay_basis ?? "rate",
            commission_percent: percent ?? profile.data?.commission_percent ?? null,
          },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["pay-profile", tutorId], data),
  });
  const saveTin = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/tutors/{id}/tax-identity", {
          params: { path: { id: tutorId } },
          body: { tin_type: tinType, tin },
        }),
      ),
    onSuccess: () => {
      setTin("");
      void queryClient.invalidateQueries({ queryKey: ["pay-profile", tutorId] });
    },
  });
  if (!profile.data) return null;
  const p = profile.data;
  const currentBasis = basis ?? p.pay_basis;
  return (
    <div className="mt-3 space-y-3 border-t border-border pt-3">
      <form
        className="space-y-2"
        aria-label={t("payrollPhase3.payBasis")}
        onSubmit={(e) => {
          e.preventDefault();
          saveBasis.mutate();
        }}
      >
        <SelectField
          label={t("payrollPhase3.payBasis")}
          value={currentBasis}
          disabled={!canManage}
          options={[
            { value: "rate", label: t("payrollPhase3.basis.rate") },
            { value: "commission", label: t("payrollPhase3.basis.commission") },
          ]}
          onChange={(e) => setBasis(e.target.value as "rate" | "commission")}
        />
        {currentBasis === "commission" ? (
          <TextField
            label={t("payrollPhase3.commissionPercent")}
            hint={t("payrollPhase3.commissionHint")}
            inputMode="decimal"
            disabled={!canManage}
            value={percent ?? p.commission_percent ?? ""}
            onChange={(e) => setPercent(e.target.value)}
          />
        ) : null}
        {canManage ? (
          <Button size="sm" type="submit" loading={saveBasis.isPending}>
            {t("payrollPhase3.save")}
          </Button>
        ) : null}
        <ErrorList error={saveBasis.error} />
      </form>
      <form
        className="space-y-2"
        aria-label={t("payrollPhase3.taxId")}
        onSubmit={(e) => {
          e.preventDefault();
          saveTin.mutate();
        }}
      >
        <p className="text-sm">
          {p.tin_hint
            ? t("payrollPhase3.taxIdOnFile", {
                type: t(`payrollPhase3.tinTypes.${p.tin_type || "ssn"}`),
                hint: p.tin_hint,
              })
            : t("payrollPhase3.noTaxId")}
        </p>
        {canManage ? (
          <>
            <div className="grid gap-2 sm:grid-cols-2">
              <SelectField
                label={t("payrollPhase3.tinType")}
                value={tinType}
                options={TIN_TYPES.map((v) => ({
                  value: v,
                  label: t(`payrollPhase3.tinTypes.${v}`),
                }))}
                onChange={(e) => setTinType(e.target.value as (typeof TIN_TYPES)[number])}
              />
              <TextField
                label={t("payrollPhase3.tin")}
                autoComplete="off"
                inputMode="numeric"
                value={tin}
                onChange={(e) => setTin(e.target.value)}
              />
            </div>
            <Button
              size="sm"
              type="submit"
              variant="secondary"
              disabled={!tin}
              loading={saveTin.isPending}
            >
              {t("payrollPhase3.saveTaxId")}
            </Button>
          </>
        ) : null}
        <ErrorList error={saveTin.error} />
      </form>
    </div>
  );
}

/** Wise Business connection for payouts (E12-T12). */
export function WiseConnectionCard() {
  const { t } = useTranslation();
  const canPay = usePermission("payroll.payrun.pay");
  const providers = useQuery({
    queryKey: ["integrations", "providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/integrations/providers")),
    enabled: canPay,
  });
  const connections = useQuery({
    queryKey: ["integrations", "connections", "payouts"],
    queryFn: async () => unwrap(await api.GET("/api/v1/integrations/connections")),
    enabled: canPay,
  });
  if (!canPay) return null;
  const wise = (connections.data?.results ?? []).find(
    (c) => c.provider === "wise" && c.status !== "disconnected",
  );
  const payoutProviders = (providers.data ?? []).filter((p) => p.capabilities.includes("payouts"));
  return (
    <section className="rounded-lg border border-border p-4" aria-labelledby="wise-heading">
      <h2 id="wise-heading" className="font-semibold">
        {t("payrollPhase3.wiseTitle")}
      </h2>
      <p className="mb-2 text-sm text-muted-foreground">{t("payrollPhase3.wiseHelp")}</p>
      {wise ? (
        <p className="text-sm">
          {t("payrollPhase3.wiseConnected", { name: wise.account_name || wise.provider_name })}
        </p>
      ) : (
        <ConnectProviders level="organisation" providers={payoutProviders} returnPath="/payroll" />
      )}
    </section>
  );
}

/** US 1099-NEC figures per tax year (E12-T12, FR-12-9). */
export function TaxFormsPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("payroll.tax.manage");
  const canSeeTin = usePermission("payroll.tax.view");
  const lastYear = new Date().getFullYear() - 1;
  const [year, setYear] = useState(lastYear);
  const summary = useQuery({
    queryKey: ["tax-forms", year],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/payroll/tax-years/{year}/1099", { params: { path: { year } } }),
      ),
  });
  const finalise = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/payroll/tax-years/{year}/1099/finalise", {
          params: { path: { year }, header: { "Idempotency-Key": `1099-${year}-${Date.now()}` } },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["tax-forms", year] }),
  });
  const years = [lastYear, lastYear - 1, lastYear - 2];
  const data = summary.data;
  return (
    <div className="max-w-5xl space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("payrollPhase3.taxFormsTitle")}</h1>
        <PayrollNav />
        <p className="text-sm text-muted-foreground">{t("payrollPhase3.taxFormsHelp")}</p>
      </header>
      <div className="flex flex-wrap items-end gap-3">
        <SelectField
          label={t("payrollPhase3.taxYear")}
          value={String(year)}
          options={years.map((y) => ({ value: String(y), label: String(y) }))}
          onChange={(e) => setYear(Number(e.target.value))}
        />
        {canManage ? (
          <Button onClick={() => finalise.mutate()} loading={finalise.isPending}>
            {t("payrollPhase3.finalise")}
          </Button>
        ) : null}
        <a className="text-sm underline" href={`/api/v1/payroll/tax-years/${year}/1099/export`}>
          {t("payrollPhase3.downloadCsv")}
        </a>
        {canSeeTin ? (
          <a
            className="text-sm underline"
            href={`/api/v1/payroll/tax-years/${year}/1099/export?full_tin=true`}
          >
            {t("payrollPhase3.downloadCsvFull")}
          </a>
        ) : null}
      </div>
      <ErrorList error={finalise.error ?? summary.error} />
      {finalise.isSuccess ? (
        <Alert tone="success">
          {t("payrollPhase3.finalised", { count: finalise.data.length })}
        </Alert>
      ) : null}
      {summary.isPending ? <Spinner label={t("common.loading")} /> : null}
      {data ? (
        <>
          <p className="text-sm">
            {t("payrollPhase3.thresholdNote", {
              threshold: formatMoney(
                { amount: data.threshold, currency: data.currency },
                i18n.language,
              ),
              count: data.reportable,
            })}
          </p>
          {data.rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("payrollPhase3.noPayments")}</p>
          ) : (
            <table className="w-full text-sm">
              <caption className="sr-only">{t("payrollPhase3.taxFormsTitle")}</caption>
              <thead>
                <tr className="text-left">
                  <th scope="col">{t("payrollPhase3.tutor")}</th>
                  <th scope="col">{t("payrollPhase3.tin")}</th>
                  <th scope="col">{t("payrollPhase3.box1")}</th>
                  <th scope="col">{t("payrollPhase3.status")}</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.tutor} className="border-t border-border">
                    <td className="py-1">{row.name}</td>
                    <td>{row.tin_hint ? `•••-••-${row.tin_hint}` : t("payrollPhase3.missing")}</td>
                    <td>{formatMoney(row.box1, i18n.language)}</td>
                    <td>
                      {!row.reportable
                        ? t("payrollPhase3.belowThreshold")
                        : row.problems.length
                          ? row.problems.map((p) => t(`payrollPhase3.problems.${p}`)).join(", ")
                          : row.filing
                            ? row.changed_since_filing
                              ? t("payrollPhase3.changed")
                              : t("payrollPhase3.filed")
                            : t("payrollPhase3.ready")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="text-xs text-muted-foreground">
            {t("payrollPhase3.generated", {
              when: formatDateTime(new Date().toISOString(), i18n.language),
            })}
          </p>
        </>
      ) : null}
    </div>
  );
}
