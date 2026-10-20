import { unwrap } from "@tutortrack/api-client";
import { formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

/** G6 (FR-04-1): add-ons bought in the app (custom domain, white-label apps, priority
 *  support): an extra item on the TutorTrack subscription that unlocks the feature. */
export function AddonsSection({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState<string | null>(null);
  const addons = useQuery({
    queryKey: ["subscription-addons"],
    queryFn: async () => unwrap(await api.GET("/api/v1/subscription/addons")),
  });
  const refresh = () => {
    for (const key of ["subscription-addons", "subscription", "entitlements", "me"]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
  const buy = useMutation({
    mutationFn: async (key: string) =>
      unwrap(
        await api.POST("/api/v1/subscription/addons/{key}", {
          params: { path: { key }, header: { "Idempotency-Key": `addon-${key}-${Date.now()}` } },
        }),
      ),
    onSuccess: () => {
      setConfirming(null);
      refresh();
    },
  });
  const stop = useMutation({
    mutationFn: async (key: string) =>
      unwrap(await api.DELETE("/api/v1/subscription/addons/{key}", { params: { path: { key } } })),
    onSuccess: refresh,
  });
  const error = buy.error ?? stop.error;
  return (
    <section aria-labelledby="addons-h" className="space-y-3">
      <h2 id="addons-h" className="text-lg font-semibold">
        {t("addons.title")}
      </h2>
      {addons.isPending ? <Spinner label={t("grid.loading")} /> : null}
      <ul className="grid gap-3 sm:grid-cols-3">
        {addons.data?.map((addon) => (
          <li key={addon.key} className="flex flex-col gap-2 rounded-md border border-border p-4">
            <p className="font-medium">{addon.name}</p>
            <p className="text-sm text-muted-foreground">{addon.description}</p>
            {addon.price ? (
              <p className="text-sm">
                {t(`addons.per.${addon.interval}`, { price: formatMoney(addon.price) })}
              </p>
            ) : null}
            {addon.included_in_plan ? (
              <p className="text-sm">{t("addons.included")}</p>
            ) : addon.active ? (
              <>
                <p className="text-sm font-medium text-success">{t("addons.active")}</p>
                {canManage ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={stop.isPending && stop.variables === addon.key}
                    onClick={() => stop.mutate(addon.key)}
                  >
                    {t("addons.stop")}
                  </Button>
                ) : null}
              </>
            ) : canManage && addon.price ? (
              confirming === addon.key ? (
                <div className="space-y-2">
                  <p className="text-sm">{t("addons.confirmText")}</p>
                  <div className="flex gap-2">
                    <Button size="sm" loading={buy.isPending} onClick={() => buy.mutate(addon.key)}>
                      {t("addons.confirm")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                      {t("addons.cancel")}
                    </Button>
                  </div>
                </div>
              ) : (
                <Button size="sm" onClick={() => setConfirming(addon.key)}>
                  {t("addons.buy")}
                </Button>
              )
            ) : null}
          </li>
        ))}
      </ul>
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
    </section>
  );
}
