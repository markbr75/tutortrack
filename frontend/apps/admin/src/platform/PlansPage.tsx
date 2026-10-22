import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PageHeader,
  PanelFooter,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
  TextField,
  UnitField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

type Plan = components["schemas"]["PlanAdmin"];
type Price = components["schemas"]["PlanAdminPrice"];

/** A compact field inside a price row (36px, field edge, tabular). */
const CELL_INPUT = "h-9 rounded-md border border-field bg-surface px-2 text-sm tabular-nums";

/** G6 (E30 FR-30-1): the plan catalogue and its prices, edited by platform staff. */
export function PlansPage() {
  const { t } = useTranslation();
  const plans = useQuery({
    queryKey: ["platform", "plans"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/plans")),
  });
  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader title={t("platformPlans.title")} description={t("platformPlans.intro")} />
      {plans.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {plans.data?.map((plan) => (
        <PlanPanel key={plan.key} plan={plan} />
      ))}
    </div>
  );
}

/** One plan: its name, visibility and trial (saved together), then its prices. */
function PlanPanel({ plan }: { plan: Plan }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState(plan.name);
  const [description, setDescription] = useState(plan.description ?? "");
  const [visibility, setVisibility] = useState(plan.visibility ?? "public");
  const [trialDays, setTrialDays] = useState(String(plan.trial_days ?? 0));
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/platform/plans/{key}", {
          params: { path: { key: plan.key } },
          body: {
            name,
            description,
            visibility,
            trial_days: Number(trialDays) || 0,
          },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["platform", "plans"] }),
  });
  const [currency, setCurrency] = useState("GBP");
  const currencies = Array.from(new Set(plan.prices.map((p) => p.currency))).sort();
  const shown = currencies.includes(currency) ? currency : (currencies[0] ?? "GBP");
  return (
    <RuledPanel
      title={plan.name}
      aside={<span className="font-mono text-xs text-muted-foreground">{plan.key}</span>}
      flush
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
          <TextField
            label={t("platformPlans.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <SelectField
            label={t("platformPlans.visibility")}
            value={visibility}
            onChange={(e) => setVisibility(e.target.value as typeof visibility)}
            options={["public", "legacy", "custom"].map((v) => ({
              value: v,
              label: t(`platformPlans.visibilities.${v}`),
            }))}
          />
          <TextField
            label={t("platformPlans.description")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <UnitField
            label={t("platformPlans.trialDays")}
            unit={t("designS11.platform.daysUnit")}
            min={0}
            value={trialDays}
            onChange={(e) => setTrialDays(e.target.value)}
          />
        </div>
        {save.error ? (
          <div className="px-5 pb-4">
            <Alert tone="danger">{save.error.message}</Alert>
          </div>
        ) : null}
        <PanelFooter>
          <Button type="submit" size="sm" loading={save.isPending}>
            {t("platformPlans.save")}
          </Button>
        </PanelFooter>
      </form>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3">
        <h3 className="font-semibold">{t("designS11.platform.prices")}</h3>
        {currencies.length > 1 ? (
          <SelectField
            label={t("platformPlans.currency")}
            hideLabel
            size="sm"
            value={shown}
            onChange={(e) => setCurrency(e.target.value)}
            options={currencies.map((c) => ({ value: c, label: c }))}
          />
        ) : currencies.length ? (
          <span className="text-muted-foreground">{shown}</span>
        ) : null}
      </div>
      {currencies.length ? (
        <p className="px-5 pb-2 text-xs text-muted-foreground md:hidden">
          {t("designS11.platform.scrollSideways")}
        </p>
      ) : null}
      {currencies.length ? (
        <RuledTable
          caption={t("platformPlans.prices", { plan: plan.name })}
          columns={[
            { header: t("platformPlans.component") },
            { header: t("platformPlans.interval") },
            { header: t("platformPlans.amount"), end: true, width: "w-36" },
            { header: t("platformPlans.included"), end: true, width: "w-28" },
            { header: t("platformPlans.stripePrice") },
            { header: t("platformPlans.save"), hidden: true },
          ]}
        >
          {plan.prices
            .filter((p) => p.currency === shown)
            .map((price) => (
              <PriceRow key={price.id} planKey={plan.key} price={price} />
            ))}
        </RuledTable>
      ) : (
        <p className="px-5 pb-4 text-sm text-muted-foreground">{t("platformPlans.noPrices")}</p>
      )}
    </RuledPanel>
  );
}

function PriceRow({ planKey, price }: { planKey: string; price: Price }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [amount, setAmount] = useState(price.unit_amount);
  const [included, setIncluded] = useState(String(price.included_quantity ?? 0));
  const [stripe, setStripe] = useState(price.stripe_price_id ?? "");
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/platform/plans/{key}/prices/{price_id}", {
          params: { path: { key: planKey, price_id: price.id } },
          body: {
            unit_amount: amount,
            included_quantity: Number(included) || 0,
            stripe_price_id: stripe,
          },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["platform", "plans"] }),
  });
  const label = `${t(`platformPlans.components.${price.component}`)} (${price.interval})`;
  return (
    <tr>
      <td className="min-w-40 align-middle">{t(`platformPlans.components.${price.component}`)}</td>
      <td className="align-middle">{t(`platformPlans.intervals.${price.interval}`)}</td>
      <td className="py-1.5 text-right align-middle">
        <input
          aria-label={t("platformPlans.amountFor", { price: label })}
          className={`${CELL_INPUT} w-28 text-right`}
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </td>
      <td className="py-1.5 text-right align-middle">
        <input
          aria-label={t("platformPlans.includedFor", { price: label })}
          className={`${CELL_INPUT} w-20 text-right`}
          inputMode="numeric"
          value={included}
          onChange={(e) => setIncluded(e.target.value)}
        />
      </td>
      <td className="py-1.5 align-middle">
        <input
          aria-label={t("platformPlans.stripeFor", { price: label })}
          className={`${CELL_INPUT} w-52 font-mono text-xs`}
          value={stripe}
          onChange={(e) => setStripe(e.target.value)}
        />
      </td>
      <td className="py-1.5 text-right align-middle whitespace-nowrap">
        <Button
          size="sm"
          variant="secondary"
          loading={save.isPending}
          onClick={() => save.mutate()}
        >
          {t("platformPlans.save")}
        </Button>
        {save.error ? (
          <span role="alert" className="block text-xs text-danger">
            {save.error.message}
          </span>
        ) : null}
      </td>
    </tr>
  );
}
