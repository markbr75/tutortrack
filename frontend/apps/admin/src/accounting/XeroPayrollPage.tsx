import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, PageHeader, RuledPanel, SelectField, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { api, usePermission } from "../api";
import { BackTrail } from "../components/RecordHeader";
import { ErrorList } from "../calendar/ErrorList";

const RETURN_PATH = "/settings/accounting/payroll";
/** Finishes the Xero Payroll OAuth connection when Xero sends the browser back here. */
function useCompletion(onDone: () => void) {
  const started = useRef(false);
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const state = params.get("state");
  const complete = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/integrations/oauth/complete", {
          body: { code: code ?? "", state: state ?? "", account_id: "" },
        }),
      ),
    onSettled: () => {
      window.history.replaceState(null, "", window.location.pathname);
      onDone();
    },
  });
  useEffect(() => {
    if (code && state && !started.current) {
      started.current = true;
      complete.mutate();
    }
  }, [code, state, complete]);
  return complete;
}

/** Xero Payroll (UK): employed tutors' hours become timesheets (E23-T10, FR-12-8). */
export function XeroPayrollPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("integrations.accounting.manage");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["xero-payroll"] });
  const complete = useCompletion(refresh);
  const status = useQuery({
    queryKey: ["xero-payroll"],
    queryFn: async () => unwrap(await api.GET("/api/v1/accounting/xero-payroll")),
  });
  const connected = Boolean(status.data?.connected);
  const employees = useQuery({
    queryKey: ["xero-payroll", "employees"],
    queryFn: async () => unwrap(await api.GET("/api/v1/accounting/xero-payroll/employees")),
    enabled: connected && canManage,
  });
  const rates = useQuery({
    queryKey: ["xero-payroll", "rates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/accounting/xero-payroll/earnings-rate")),
    enabled: connected && canManage,
  });
  const connect = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/integrations/oauth/start", {
          body: { provider: "xero_payroll", level: "organisation", next: RETURN_PATH },
        }),
      ),
    onSuccess: (result) => window.location.assign(result.authorize_url),
  });
  const match = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/accounting/xero-payroll/match")),
    onSuccess: (data) => queryClient.setQueryData(["xero-payroll"], data),
  });
  const link = useMutation({
    mutationFn: async ({ tutor, employee }: { tutor: string; employee: string }) =>
      unwrap(
        await api.PUT("/api/v1/accounting/xero-payroll/links", {
          body: { tutor, employee_id: employee },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["xero-payroll"], data),
  });
  const rate = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.PUT("/api/v1/accounting/xero-payroll/earnings-rate", {
          body: { id, name: rates.data?.find((r) => r.id === id)?.name ?? "" },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["xero-payroll"], data),
  });
  const resync = useMutation({
    mutationFn: async (payRun: string) =>
      unwrap(
        await api.POST("/api/v1/accounting/xero-payroll/sync", {
          body: { pay_run: payRun },
          params: { header: { "Idempotency-Key": `xero-payroll-${payRun}-${Date.now()}` } },
        }),
      ),
    onSuccess: refresh,
  });
  const [picked, setPicked] = useState<Record<string, string>>({});
  const data = status.data;
  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <BackTrail>
          <Link to="/settings/accounting">{t("accounting.title")}</Link>
        </BackTrail>
        <PageHeader
          title={t("accountingPhase3.payrollTitle")}
          description={t("accountingPhase3.payrollHelp")}
        />
      </div>
      {complete.isSuccess ? (
        <Alert tone="success">{t("accountingPhase3.payrollConnected")}</Alert>
      ) : null}
      <ErrorList
        error={
          complete.error ??
          status.error ??
          connect.error ??
          match.error ??
          link.error ??
          rate.error ??
          resync.error
        }
      />
      {status.isPending ? <Spinner label={t("common.loading")} /> : null}
      {data && !data.connected ? (
        <RuledPanel
          footer={
            canManage ? (
              <Button onClick={() => connect.mutate()} loading={connect.isPending}>
                {t("accountingPhase3.connectPayroll")}
              </Button>
            ) : undefined
          }
        >
          <p className="text-sm text-muted-foreground">
            {t("accountingPhase3.payrollNotConnected")}
          </p>
        </RuledPanel>
      ) : null}
      {data?.connected ? (
        <>
          <p className="text-sm">
            {t("accountingPhase3.payrollAccount", { name: data.account_name || "Xero" })}
          </p>
          <RuledPanel titleId="rate-heading" title={t("accountingPhase3.earningsRate")}>
            {rates.data ? (
              <div className="max-w-md">
                <SelectField
                  label={t("accountingPhase3.earningsRate")}
                  hint={t("accountingPhase3.earningsRateHint")}
                  disabled={!canManage}
                  value={data.earnings_rate?.id ?? ""}
                  options={[
                    { value: "", label: t("accountingPhase3.firstOrdinary") },
                    ...rates.data.map((r) => ({ value: r.id, label: r.name })),
                  ]}
                  onChange={(e) => e.target.value && rate.mutate(e.target.value)}
                />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {data.earnings_rate?.name ?? t("accountingPhase3.firstOrdinary")}
              </p>
            )}
          </RuledPanel>
          <RuledPanel
            flush
            titleId="employees-heading"
            title={t("accountingPhase3.employees")}
            aside={
              canManage ? (
                <Button size="sm" variant="secondary" onClick={() => match.mutate()}>
                  {t("accountingPhase3.matchByEmail")}
                </Button>
              ) : undefined
            }
          >
            {data.links.length ? (
              <ul className="text-sm">
                {data.links.map((l) => (
                  <li key={l.tutor} className="border-b border-rule px-5 py-2.5">
                    {t("accountingPhase3.linked", {
                      tutor: l.tutor_name,
                      employee: l.name || l.employee_id,
                    })}
                  </li>
                ))}
              </ul>
            ) : null}
            {data.unlinked.length ? (
              <ul className="text-sm" aria-label={t("accountingPhase3.unlinked")}>
                {data.unlinked.map((u) => (
                  <li
                    key={u.tutor}
                    className="flex flex-wrap items-end gap-2 border-b border-rule px-5 py-3 last:border-0"
                  >
                    <div className="min-w-56 flex-1 sm:max-w-sm">
                      <SelectField
                        label={t("accountingPhase3.employeeFor", { tutor: u.tutor_name })}
                        value={picked[u.tutor] ?? ""}
                        disabled={!canManage}
                        options={[
                          { value: "", label: t("accountingPhase3.choose") },
                          ...(employees.data ?? []).map((e) => ({
                            value: e.id,
                            label: `${e.first_name} ${e.last_name}`.trim() || e.email,
                          })),
                        ]}
                        onChange={(e) => setPicked({ ...picked, [u.tutor]: e.target.value })}
                      />
                    </div>
                    <Button
                      variant="secondary"
                      disabled={!canManage || !picked[u.tutor]}
                      onClick={() =>
                        link.mutate({ tutor: u.tutor, employee: picked[u.tutor] ?? "" })
                      }
                    >
                      {t("accountingPhase3.link")}
                    </Button>
                  </li>
                ))}
              </ul>
            ) : null}
            {!data.links.length && !data.unlinked.length ? (
              <p className="px-5 py-4 text-sm text-muted-foreground">
                {t("designS7.accounting.noEmployees")}
              </p>
            ) : null}
          </RuledPanel>
          <RuledPanel flush titleId="syncs-heading" title={t("accountingPhase3.syncs")}>
            {data.syncs.length === 0 ? (
              <p className="px-5 py-4 text-sm text-muted-foreground">
                {t("accountingPhase3.noSyncs")}
              </p>
            ) : (
              <ul className="text-sm">
                {data.syncs.map((s) => (
                  <li
                    key={s.id}
                    className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-t border-rule px-5 py-2.5 first:border-0"
                  >
                    <div className="min-w-0">
                      <p className="font-medium tabular-nums">{s.pay_run_number}</p>
                      <p className="text-xs text-muted-foreground tabular-nums">
                        {t(`accountingPhase3.syncStatus.${s.status}`)}
                        {s.synced_at ? ` · ${formatDateTime(s.synced_at, i18n.language)}` : ""}
                      </p>
                      {s.error ? <p className="text-xs text-danger">{s.error}</p> : null}
                    </div>
                    {canManage && s.status !== "synced" ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => resync.mutate(s.pay_run)}
                      >
                        {t("accountingPhase3.sendAgain")}
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </RuledPanel>
        </>
      ) : null}
    </div>
  );
}
