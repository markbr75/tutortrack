import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { SelectField } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { KeyedSettings } from "./KeyedSettings";

/** Gap G3 payment options (FR-11-1..3): auto-pay timing and expiring-card notices for the
 * organisation, and per branch the ways it takes payment and an optional card surcharge
 * (refused where the law doesn't allow it). */
export function PaymentOptions() {
  const { t } = useTranslation();
  const branches = useQuery({
    queryKey: ["g3", "branches"],
    queryFn: async () => unwrap(await api.GET("/api/v1/branches")).results,
  });
  const [branch, setBranch] = useState("");
  const chosen = branch || branches.data?.[0]?.id || "";
  return (
    <div className="space-y-6">
      <section
        aria-labelledby="g3-autopay"
        className="space-y-2 rounded-md border border-border p-4"
      >
        <h2 id="g3-autopay" className="font-semibold">
          {t("g3.paymentOptions.autopay")}
        </h2>
        <KeyedSettings
          area="payments"
          keys={[
            "payments.autopay_timing",
            "payments.autopay_days_before_due",
            "payments.card_expiry_notices",
          ]}
          label={t("g3.paymentOptions.autopay")}
        />
      </section>
      <section
        aria-labelledby="g3-methods"
        className="space-y-2 rounded-md border border-border p-4"
      >
        <h2 id="g3-methods" className="font-semibold">
          {t("g3.paymentOptions.methods")}
        </h2>
        <p className="text-sm text-muted-foreground">{t("g3.paymentOptions.methodsHelp")}</p>
        {(branches.data?.length ?? 0) > 1 ? (
          <SelectField
            label={t("g3.paymentOptions.branch")}
            value={chosen}
            onChange={(e) => setBranch(e.target.value)}
            options={(branches.data ?? []).map((b) => ({ value: b.id, label: b.name }))}
          />
        ) : null}
        {chosen ? (
          <KeyedSettings
            key={chosen}
            area="payments"
            branch={chosen}
            keys={["payments.enabled_methods", "payments.card_surcharge_percent"]}
            label={t("g3.paymentOptions.methods")}
            optionLabel={(_key, value) => t(`g3.paymentOptions.method.${value}`)}
          />
        ) : null}
      </section>
    </div>
  );
}
