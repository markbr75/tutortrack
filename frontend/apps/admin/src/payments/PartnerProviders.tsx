import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, RuledPanel } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type Partner = "gocardless" | "paypal";
const PARTNERS: Partner[] = ["gocardless", "paypal"];
const NAMES: Record<Partner, string> = { gocardless: "GoCardless", paypal: "PayPal" };

/** What GoCardless (``code``) or PayPal (``merchantIdInPayPal``) added to our URL. */
function returnedConnection(): { provider: Partner; state: string; code: string } | null {
  const params = new URLSearchParams(window.location.search);
  const provider = params.get("provider");
  if (provider !== "gocardless" && provider !== "paypal") return null;
  const state = params.get("state") ?? params.get("merchantId") ?? "";
  const code = params.get("code") ?? params.get("merchantIdInPayPal") ?? "";
  return state && code ? { provider, state, code } : null;
}

/** Settings → Payments: GoCardless (Direct Debit) and PayPal, connected through each
 * provider's own sign-up pages (E11-T11/T12). */
export function PartnerProviders() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("payments.provider.manage");
  const providers = useQuery({
    queryKey: ["payment-providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/payments/providers")),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["payment-providers"] });
  const connect = useMutation({
    mutationFn: async (provider: Partner) =>
      unwrap(
        await api.POST("/api/v1/payments/providers/{provider}/connect", {
          params: { path: { provider } },
          body: { email: "" },
        }),
      ),
    onSuccess: (result) => window.location.assign(result.url),
  });
  const complete = useMutation({
    mutationFn: async (input: { provider: Partner; state: string; code: string }) =>
      unwrap(
        await api.POST("/api/v1/payments/providers/{provider}/complete", {
          params: { path: { provider: input.provider } },
          body: { state: input.state, code: input.code },
        }),
      ),
    onSuccess: () => {
      window.history.replaceState(null, "", window.location.pathname);
      refresh();
    },
  });
  const disconnect = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/payments/providers/{id}/disconnect", {
          params: { path: { id } },
        }),
      ),
    onSuccess: refresh,
  });

  useEffect(() => {
    const back = returnedConnection();
    if (back) complete.mutate(back);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on arrival
  }, []);

  return (
    <section className="space-y-3" aria-label={t("paymentProviders.title")}>
      <h2 className="text-base font-semibold">{t("paymentProviders.title")}</h2>
      {complete.isSuccess ? <Alert tone="success">{t("paymentProviders.connected")}</Alert> : null}
      <div className="grid gap-4 md:grid-cols-2">
        {PARTNERS.map((provider) => {
          const account = providers.data?.find((p) => p.provider === provider && !p.branch);
          return (
            <RuledPanel
              key={provider}
              level={3}
              title={NAMES[provider]}
              description={t(`paymentProviders.${provider}Help`)}
              aside={
                account ? (
                  <span className="text-muted-foreground">
                    {t(`payments.accountStatus.${account.status}`)}
                  </span>
                ) : null
              }
              footer={
                canManage ? (
                  !account || account.status === "pending" ? (
                    <Button
                      size="sm"
                      onClick={() => connect.mutate(provider)}
                      disabled={connect.isPending}
                    >
                      {t("paymentProviders.connect", { name: NAMES[provider] })}
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => disconnect.mutate(account.id)}
                    >
                      {t("payments.disconnect")}
                    </Button>
                  )
                ) : undefined
              }
            >
              <p className="text-sm text-muted-foreground tabular-nums">
                {account ? account.account_ref : t("designS7.payments.notConnected")}
              </p>
            </RuledPanel>
          );
        })}
      </div>
      <ErrorList error={connect.error ?? complete.error ?? disconnect.error} />
    </section>
  );
}
