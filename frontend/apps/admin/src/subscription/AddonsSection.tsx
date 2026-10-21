import { unwrap } from "@tutortrack/api-client";
import { formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, RuledPanel, Spinner } from "@tutortrack/ui";
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
    <RuledPanel flush titleId="addons-h" title={t("addons.title")}>
      {addons.isPending ? (
        <div className="px-5 py-4">
          <Spinner label={t("grid.loading")} />
        </div>
      ) : null}
      <ul className="text-sm">
        {addons.data?.map((addon) => (
          <li
            key={addon.key}
            className="grid gap-x-6 gap-y-2 border-t border-rule px-5 py-3.5 first:border-0 sm:grid-cols-[minmax(0,1fr)_10rem_10rem] sm:items-start"
          >
            <div className="min-w-0">
              <p className="font-semibold">{addon.name}</p>
              <p className="text-xs text-muted-foreground">{addon.description}</p>
            </div>
            <p className="tabular-nums sm:text-right">
              {addon.price
                ? t(`addons.per.${addon.interval}`, { price: formatMoney(addon.price) })
                : null}
            </p>
            <div className="space-y-2 sm:text-right">
              {addon.included_in_plan ? (
                <p>{t("addons.included")}</p>
              ) : addon.active ? (
                <>
                  <p className="font-semibold">{t("addons.active")}</p>
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
                  <>
                    <p className="sm:text-left">{t("addons.confirmText")}</p>
                    <div className="flex flex-wrap gap-2 sm:justify-end">
                      <Button
                        size="sm"
                        loading={buy.isPending}
                        onClick={() => buy.mutate(addon.key)}
                      >
                        {t("addons.confirm")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                        {t("addons.cancel")}
                      </Button>
                    </div>
                  </>
                ) : (
                  <Button size="sm" variant="secondary" onClick={() => setConfirming(addon.key)}>
                    {t("addons.buy")}
                  </Button>
                )
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      {error ? (
        <div className="px-5 pb-4">
          <Alert tone="danger">{error.message}</Alert>
        </div>
      ) : null}
    </RuledPanel>
  );
}
