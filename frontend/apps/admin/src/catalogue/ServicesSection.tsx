import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { PAGE, formatRate } from "./format";
import { Cell, MutationError, QueryState, Table } from "./shared";

type Service = components["schemas"]["Service"];
type PricingUnit = components["schemas"]["PricingUnitEnum"];
type Format = components["schemas"]["FormatEnum"];
type PayUnit = components["schemas"]["PayUnitEnum"];
type GroupCharge = components["schemas"]["GroupChargeEnum"];

const UNITS: PricingUnit[] = [
  "per_hour",
  "per_lesson",
  "per_student_per_lesson",
  "per_month",
  "per_term",
];
const FORMATS: Format[] = ["one_to_one", "small_group", "class"];

interface Draft {
  name: string;
  format: Format;
  max_students: string;
  pricing_unit: PricingUnit;
  group_charge: GroupCharge;
  default_duration_minutes: string;
  charge: string;
  pay_mode: "rate" | "percent" | "none";
  pay: string;
  pay_unit: PayUnit;
  tax_rate: string;
}

const EMPTY: Draft = {
  name: "",
  format: "one_to_one",
  max_students: "1",
  pricing_unit: "per_hour",
  group_charge: "per_student",
  default_duration_minutes: "60",
  charge: "",
  pay_mode: "rate",
  pay: "",
  pay_unit: "per_hour",
  tax_rate: "",
};

function fromService(s: Service): Draft {
  return {
    name: s.name,
    format: s.format ?? "one_to_one",
    max_students: String(s.max_students ?? 1),
    pricing_unit: s.pricing_unit ?? "per_hour",
    group_charge: s.group_charge ?? "per_student",
    default_duration_minutes: String(s.default_duration_minutes ?? 60),
    charge: s.charge_rate ? String(Number(s.charge_rate.amount)) : "",
    pay_mode: s.pay_rate ? "rate" : s.pay_percent ? "percent" : "none",
    pay: s.pay_rate ? String(Number(s.pay_rate.amount)) : (s.pay_percent ?? ""),
    pay_unit: s.pay_unit ?? "per_hour",
    tax_rate: s.tax_rate ?? "",
  };
}

/** Services and their default rates (FR-06-2). */
export function ServicesSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("catalogue.manage");
  const canRates = usePermission("rates.manage");
  const canSeeCharge = usePermission("billing.rates.view_charge");
  const canSeePay = usePermission("billing.rates.view_pay");
  const { data: org } = useOrganisation();
  const currency = org?.default_currency ?? "GBP";
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const services = useQuery({
    queryKey: ["catalogue", "services"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/services", { params: { query: PAGE } })),
  });
  const taxRates = useQuery({
    queryKey: ["catalogue", "tax-rates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/catalogue/tax-rates")),
  });
  const save = useMutation({
    mutationFn: async () => {
      const group = draft.format !== "one_to_one";
      const body = {
        name: draft.name,
        format: draft.format,
        max_students: group ? Number(draft.max_students) : 1,
        pricing_unit: draft.pricing_unit,
        group_charge: draft.group_charge,
        default_duration_minutes: Number(draft.default_duration_minutes),
        pay_unit: draft.pay_unit,
        tax_rate: draft.tax_rate || null,
        ...(canRates
          ? {
              charge_rate: { amount: draft.charge || "0", currency },
              pay_rate:
                draft.pay_mode === "rate" && draft.pay ? { amount: draft.pay, currency } : null,
              pay_percent: draft.pay_mode === "percent" && draft.pay ? draft.pay : null,
            }
          : {}),
      };
      return editing
        ? unwrap(
            await api.PATCH("/api/v1/catalogue/services/{id}", {
              params: { path: { id: editing } },
              body,
            }),
          )
        : unwrap(
            await api.POST("/api/v1/catalogue/services", {
              body: { ...body, charge_rate: body.charge_rate ?? { amount: "0", currency } },
            }),
          );
    },
    onSuccess: () => {
      setDraft(EMPTY);
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ["catalogue", "services"] });
    },
  });
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const unitLabel = (u: string) => t(`catalogue.services.unit.${u}`);

  const headers = [
    t("catalogue.name"),
    t("catalogue.services.pricing"),
    ...(canSeeCharge ? [t("catalogue.services.charge")] : []),
    ...(canSeePay ? [t("catalogue.services.pay")] : []),
    t("catalogue.services.status"),
    ...(canManage ? [t("catalogue.actions")] : []),
  ];

  return (
    <div className="space-y-6">
      <QueryState query={services}>
        <Table caption={t("catalogue.tabs.services")} headers={headers}>
          {(services.data?.results ?? []).map((s) => (
            <tr key={s.id}>
              <Cell>{s.name}</Cell>
              <Cell>
                {unitLabel(s.pricing_unit ?? "per_hour")} ·{" "}
                {t(`catalogue.services.format.${s.format ?? "one_to_one"}`)}
              </Cell>
              {canSeeCharge ? <Cell>{formatRate(s.charge_rate, i18n.language)}</Cell> : null}
              {canSeePay ? (
                <Cell>
                  {s.pay_rate
                    ? formatRate(s.pay_rate, i18n.language)
                    : s.pay_percent
                      ? t("catalogue.services.percentOfCharge", { percent: Number(s.pay_percent) })
                      : "–"}
                </Cell>
              ) : null}
              <Cell>{s.active === false ? t("catalogue.inactive") : t("catalogue.active")}</Cell>
              {canManage ? (
                <Cell>
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-label={t("catalogue.editNamed", { name: s.name })}
                    onClick={() => {
                      setEditing(s.id);
                      setDraft(fromService(s));
                    }}
                  >
                    {t("catalogue.edit")}
                  </Button>
                </Cell>
              ) : null}
            </tr>
          ))}
        </Table>
      </QueryState>

      {canManage ? (
        <form
          className="space-y-4 rounded-lg border border-border p-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <h2 className="font-semibold">
            {editing ? t("catalogue.services.edit") : t("catalogue.services.new")}
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <TextField
              label={t("catalogue.name")}
              required
              value={draft.name}
              onChange={(e) => set({ name: e.target.value })}
            />
            <SelectField
              label={t("catalogue.services.formatLabel")}
              value={draft.format}
              onChange={(e) => set({ format: e.target.value as Format })}
              options={FORMATS.map((f) => ({
                value: f,
                label: t(`catalogue.services.format.${f}`),
              }))}
            />
            {draft.format !== "one_to_one" ? (
              <>
                <TextField
                  label={t("catalogue.services.maxStudents")}
                  type="number"
                  min={2}
                  value={draft.max_students}
                  onChange={(e) => set({ max_students: e.target.value })}
                />
                <SelectField
                  label={t("catalogue.services.groupCharge")}
                  value={draft.group_charge}
                  onChange={(e) => set({ group_charge: e.target.value as GroupCharge })}
                  options={(["per_student", "split"] as const).map((g) => ({
                    value: g,
                    label: t(`catalogue.services.group.${g}`),
                  }))}
                />
              </>
            ) : null}
            <TextField
              label={t("catalogue.services.duration")}
              type="number"
              min={5}
              max={600}
              value={draft.default_duration_minutes}
              onChange={(e) => set({ default_duration_minutes: e.target.value })}
            />
            <SelectField
              label={t("catalogue.services.pricing")}
              value={draft.pricing_unit}
              onChange={(e) => set({ pricing_unit: e.target.value as PricingUnit })}
              options={UNITS.map((u) => ({ value: u, label: unitLabel(u) }))}
            />
            <SelectField
              label={t("catalogue.services.taxRate")}
              value={draft.tax_rate}
              onChange={(e) => set({ tax_rate: e.target.value })}
              options={[
                { value: "", label: t("catalogue.services.defaultTax") },
                ...(taxRates.data ?? []).map((r) => ({
                  value: r.id,
                  label: `${r.name} (${Number(r.percent)}%)`,
                })),
              ]}
            />
          </div>
          {canRates ? (
            <fieldset className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <legend className="mb-2 text-sm font-medium">
                {t("catalogue.services.rates", { currency })}
              </legend>
              <TextField
                label={t("catalogue.services.charge")}
                inputMode="decimal"
                required
                value={draft.charge}
                onChange={(e) => set({ charge: e.target.value })}
              />
              <SelectField
                label={t("catalogue.services.payMode")}
                value={draft.pay_mode}
                onChange={(e) => set({ pay_mode: e.target.value as Draft["pay_mode"] })}
                options={(["rate", "percent", "none"] as const).map((m) => ({
                  value: m,
                  label: t(`catalogue.services.payModes.${m}`),
                }))}
              />
              {draft.pay_mode !== "none" ? (
                <TextField
                  label={
                    draft.pay_mode === "rate"
                      ? t("catalogue.services.pay")
                      : t("catalogue.services.payPercent")
                  }
                  inputMode="decimal"
                  value={draft.pay}
                  onChange={(e) => set({ pay: e.target.value })}
                />
              ) : null}
              {draft.pay_mode === "rate" ? (
                <SelectField
                  label={t("catalogue.services.payUnit")}
                  value={draft.pay_unit}
                  onChange={(e) => set({ pay_unit: e.target.value as PayUnit })}
                  options={(["per_hour", "per_lesson"] as const).map((u) => ({
                    value: u,
                    label: unitLabel(u),
                  }))}
                />
              ) : null}
            </fieldset>
          ) : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={save.isPending}>
              {editing ? t("catalogue.save") : t("catalogue.services.create")}
            </Button>
            {editing ? (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setEditing(null);
                  setDraft(EMPTY);
                }}
              >
                {t("catalogue.cancel")}
              </Button>
            ) : null}
          </div>
          <MutationError error={save.error} />
        </form>
      ) : null}
    </div>
  );
}
