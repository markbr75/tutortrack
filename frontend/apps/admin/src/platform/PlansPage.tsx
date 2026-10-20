import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

type Plan = components["schemas"]["PlanAdmin"];
type Price = components["schemas"]["PlanAdminPrice"];

/** G6 (E30 FR-30-1): the plan catalogue and its prices, edited by platform staff. */
export function PlansPage() {
  const { t } = useTranslation();
  const plans = useQuery({
    queryKey: ["platform", "plans"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/plans")),
  });
  return (
    <div className="max-w-5xl space-y-4">
      <h1 className="text-2xl font-semibold">{t("platformPlans.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("platformPlans.intro")}</p>
      {plans.isPending ? <Spinner label={t("grid.loading")} /> : null}
      <ul className="space-y-4">
        {plans.data?.map((plan) => (
          <PlanCard key={plan.key} plan={plan} />
        ))}
      </ul>
    </div>
  );
}

function PlanCard({ plan }: { plan: Plan }) {
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
  return (
    <li className="space-y-3 rounded-lg border border-border p-4">
      <h2 className="text-lg font-semibold">
        {plan.name} <span className="font-mono text-sm text-muted-foreground">{plan.key}</span>
      </h2>
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
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
        <TextField
          label={t("platformPlans.trialDays")}
          type="number"
          min={0}
          value={trialDays}
          onChange={(e) => setTrialDays(e.target.value)}
        />
        <div>
          <Button type="submit" size="sm" loading={save.isPending}>
            {t("platformPlans.save")}
          </Button>
        </div>
      </form>
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
      {currencies.length ? (
        <>
          <SelectField
            label={t("platformPlans.currency")}
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            options={currencies.map((c) => ({ value: c, label: c }))}
          />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">
                {t("platformPlans.prices", { plan: plan.name })}
              </caption>
              <thead>
                <tr className="text-left">
                  <th scope="col">{t("platformPlans.component")}</th>
                  <th scope="col">{t("platformPlans.interval")}</th>
                  <th scope="col">{t("platformPlans.amount")}</th>
                  <th scope="col">{t("platformPlans.included")}</th>
                  <th scope="col">{t("platformPlans.stripePrice")}</th>
                  <th scope="col">
                    <span className="sr-only">{t("platformPlans.save")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {plan.prices
                  .filter((p) => p.currency === currency)
                  .map((price) => (
                    <PriceRow key={price.id} planKey={plan.key} price={price} />
                  ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">{t("platformPlans.noPrices")}</p>
      )}
    </li>
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
    <tr className="border-t border-border">
      <td>{t(`platformPlans.components.${price.component}`)}</td>
      <td>{t(`platformPlans.intervals.${price.interval}`)}</td>
      <td>
        <input
          aria-label={t("platformPlans.amountFor", { price: label })}
          className="h-9 w-28 rounded-md border border-border bg-background px-2"
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </td>
      <td>
        <input
          aria-label={t("platformPlans.includedFor", { price: label })}
          className="h-9 w-20 rounded-md border border-border bg-background px-2"
          inputMode="numeric"
          value={included}
          onChange={(e) => setIncluded(e.target.value)}
        />
      </td>
      <td>
        <input
          aria-label={t("platformPlans.stripeFor", { price: label })}
          className="h-9 w-48 rounded-md border border-border bg-background px-2 font-mono"
          value={stripe}
          onChange={(e) => setStripe(e.target.value)}
        />
      </td>
      <td>
        <Button
          size="sm"
          variant="secondary"
          loading={save.isPending}
          onClick={() => save.mutate()}
        >
          {t("platformPlans.save")}
        </Button>
        {save.error ? (
          <span role="alert" className="ml-2 text-danger">
            {save.error.message}
          </span>
        ) : null}
      </td>
    </tr>
  );
}
