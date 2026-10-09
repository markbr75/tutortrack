import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { PAGE, formatRate } from "./format";
import { Cell, MutationError, QueryState, Table } from "./shared";

function AddForm({
  title,
  onSubmit,
  pending,
  error,
  children,
}: {
  title: string;
  onSubmit: () => void;
  pending: boolean;
  error: unknown;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <form
      className="space-y-3 rounded-lg border border-border p-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h2 className="font-semibold">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
      <Button type="submit" disabled={pending}>
        {t("catalogue.add")}
      </Button>
      <MutationError error={error} />
    </form>
  );
}

function useCatalogueMutation<T>(key: string, fn: () => Promise<T>, reset: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      reset();
      void queryClient.invalidateQueries({ queryKey: ["catalogue", key] });
    },
  });
}

/** Tax rates (FR-06-3). */
export function TaxRatesSection() {
  const { t } = useTranslation();
  const canManage = usePermission("rates.manage");
  const [draft, setDraft] = useState({ name: "", percent: "", exempt_reason: "" });
  const rates = useQuery({
    queryKey: ["catalogue", "tax-rates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/catalogue/tax-rates")),
  });
  const add = useCatalogueMutation(
    "tax-rates",
    async () => unwrap(await api.POST("/api/v1/catalogue/tax-rates", { body: draft })),
    () => setDraft({ name: "", percent: "", exempt_reason: "" }),
  );
  const queryClient = useQueryClient();
  const setDefault = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.PATCH("/api/v1/catalogue/tax-rates/{id}", {
          params: { path: { id } },
          body: { is_default: true },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["catalogue", "tax-rates"] }),
  });
  return (
    <div className="space-y-6">
      <QueryState query={rates}>
        <Table
          caption={t("catalogue.tabs.tax")}
          headers={[
            t("catalogue.name"),
            t("catalogue.tax.percent"),
            t("catalogue.tax.exemptReason"),
            t("catalogue.tax.default"),
          ]}
        >
          {(rates.data ?? []).map((rate) => (
            <tr key={rate.id}>
              <Cell>{rate.name}</Cell>
              <Cell>{Number(rate.percent)}%</Cell>
              <Cell>{rate.exempt_reason}</Cell>
              <Cell>
                {rate.is_default ? (
                  t("catalogue.tax.isDefault")
                ) : canManage ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-label={t("catalogue.tax.makeDefaultNamed", { name: rate.name })}
                    onClick={() => setDefault.mutate(rate.id)}
                  >
                    {t("catalogue.tax.makeDefault")}
                  </Button>
                ) : null}
              </Cell>
            </tr>
          ))}
        </Table>
      </QueryState>
      {canManage ? (
        <AddForm
          title={t("catalogue.tax.new")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error}
        >
          <TextField
            label={t("catalogue.name")}
            required
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
          <TextField
            label={t("catalogue.tax.percent")}
            inputMode="decimal"
            required
            value={draft.percent}
            onChange={(e) => setDraft((d) => ({ ...d, percent: e.target.value }))}
          />
          <TextField
            label={t("catalogue.tax.exemptReason")}
            value={draft.exempt_reason}
            onChange={(e) => setDraft((d) => ({ ...d, exempt_reason: e.target.value }))}
          />
        </AddForm>
      ) : null}
    </div>
  );
}

type LocationType = components["schemas"]["LocationTypeEnum"];
const LOCATION_TYPES: LocationType[] = [
  "centre",
  "client_home",
  "tutor_home",
  "school",
  "online",
  "other",
];

/** Locations (FR-06-10). */
export function LocationsSection() {
  const { t } = useTranslation();
  const canManage = usePermission("catalogue.manage");
  const empty = { name: "", type: "centre" as LocationType, line1: "", city: "", postcode: "" };
  const [draft, setDraft] = useState(empty);
  const locations = useQuery({
    queryKey: ["catalogue", "locations"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/locations", { params: { query: PAGE } })),
  });
  const add = useCatalogueMutation(
    "locations",
    async () =>
      unwrap(
        await api.POST("/api/v1/catalogue/locations", {
          body: {
            name: draft.name,
            type: draft.type,
            ...(draft.type === "online"
              ? {}
              : {
                  address_input: { line1: draft.line1, city: draft.city, postcode: draft.postcode },
                }),
          },
        }),
      ),
    () => setDraft(empty),
  );
  return (
    <div className="space-y-6">
      <QueryState query={locations}>
        <Table
          caption={t("catalogue.tabs.locations")}
          headers={[
            t("catalogue.name"),
            t("catalogue.locations.type"),
            t("catalogue.locations.address"),
          ]}
        >
          {(locations.data?.results ?? []).map((l) => (
            <tr key={l.id}>
              <Cell>{l.name}</Cell>
              <Cell>{t(`catalogue.locations.types.${l.type ?? "centre"}`)}</Cell>
              <Cell>
                {l.address
                  ? [l.address.line1, l.address.city, l.address.postcode].filter(Boolean).join(", ")
                  : ""}
              </Cell>
            </tr>
          ))}
        </Table>
      </QueryState>
      {canManage ? (
        <AddForm
          title={t("catalogue.locations.new")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error}
        >
          <TextField
            label={t("catalogue.name")}
            required
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
          <SelectField
            label={t("catalogue.locations.type")}
            value={draft.type}
            onChange={(e) => setDraft((d) => ({ ...d, type: e.target.value as LocationType }))}
            options={LOCATION_TYPES.map((v) => ({
              value: v,
              label: t(`catalogue.locations.types.${v}`),
            }))}
          />
          {draft.type !== "online" ? (
            <>
              <TextField
                label={t("people.address.line1")}
                value={draft.line1}
                onChange={(e) => setDraft((d) => ({ ...d, line1: e.target.value }))}
              />
              <TextField
                label={t("people.address.city")}
                value={draft.city}
                onChange={(e) => setDraft((d) => ({ ...d, city: e.target.value }))}
              />
              <TextField
                label={t("people.address.postcode")}
                value={draft.postcode}
                onChange={(e) => setDraft((d) => ({ ...d, postcode: e.target.value }))}
              />
            </>
          ) : null}
        </AddForm>
      ) : null}
    </div>
  );
}

type ProductCategory = components["schemas"]["ProductCategoryEnum"];
const PRODUCT_CATEGORIES: ProductCategory[] = [
  "registration",
  "materials",
  "books",
  "exam_entry",
  "late_cancel",
  "travel",
  "other",
];

/** Fees and products (FR-06-9). */
export function ProductsSection() {
  const { t, i18n } = useTranslation();
  const canManage = usePermission("catalogue.manage");
  const { data: org } = useOrganisation();
  const currency = org?.default_currency ?? "GBP";
  const empty = {
    name: "",
    category: "other" as ProductCategory,
    price: "",
    tutor_share_percent: "0",
  };
  const [draft, setDraft] = useState(empty);
  const products = useQuery({
    queryKey: ["catalogue", "products"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/products", { params: { query: PAGE } })),
  });
  const add = useCatalogueMutation(
    "products",
    async () =>
      unwrap(
        await api.POST("/api/v1/catalogue/products", {
          body: {
            name: draft.name,
            category: draft.category,
            price: { amount: draft.price || "0", currency },
            tutor_share_percent: draft.tutor_share_percent || "0",
          },
        }),
      ),
    () => setDraft(empty),
  );
  return (
    <div className="space-y-6">
      <QueryState query={products}>
        <Table
          caption={t("catalogue.tabs.products")}
          headers={[
            t("catalogue.name"),
            t("catalogue.products.category"),
            t("catalogue.products.price"),
            t("catalogue.products.tutorShare"),
          ]}
        >
          {(products.data?.results ?? []).map((p) => (
            <tr key={p.id}>
              <Cell>{p.name}</Cell>
              <Cell>{t(`catalogue.products.categories.${p.category ?? "other"}`)}</Cell>
              <Cell>{formatRate(p.price, i18n.language)}</Cell>
              <Cell>{Number(p.tutor_share_percent ?? 0)}%</Cell>
            </tr>
          ))}
        </Table>
      </QueryState>
      {canManage ? (
        <AddForm
          title={t("catalogue.products.new")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error}
        >
          <TextField
            label={t("catalogue.name")}
            required
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
          <SelectField
            label={t("catalogue.products.category")}
            value={draft.category}
            onChange={(e) =>
              setDraft((d) => ({ ...d, category: e.target.value as ProductCategory }))
            }
            options={PRODUCT_CATEGORIES.map((v) => ({
              value: v,
              label: t(`catalogue.products.categories.${v}`),
            }))}
          />
          <TextField
            label={t("catalogue.products.priceIn", { currency })}
            inputMode="decimal"
            required
            value={draft.price}
            onChange={(e) => setDraft((d) => ({ ...d, price: e.target.value }))}
          />
          <TextField
            label={t("catalogue.products.tutorShare")}
            inputMode="decimal"
            value={draft.tutor_share_percent}
            onChange={(e) => setDraft((d) => ({ ...d, tutor_share_percent: e.target.value }))}
          />
        </AddForm>
      ) : null}
    </div>
  );
}

type QuantityType = components["schemas"]["QuantityTypeEnum"];

/** Package templates (FR-06-8). */
export function PackagesSection() {
  const { t, i18n } = useTranslation();
  const canManage = usePermission("catalogue.manage");
  const { data: org } = useOrganisation();
  const currency = org?.default_currency ?? "GBP";
  const empty = {
    name: "",
    quantity_type: "hours" as QuantityType,
    quantity: "",
    price: "",
    validity_days: "",
  };
  const [draft, setDraft] = useState(empty);
  const packages = useQuery({
    queryKey: ["catalogue", "packages"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/packages", { params: { query: PAGE } })),
  });
  const add = useCatalogueMutation(
    "packages",
    async () =>
      unwrap(
        await api.POST("/api/v1/catalogue/packages", {
          body: {
            name: draft.name,
            quantity_type: draft.quantity_type,
            quantity: draft.quantity,
            price: { amount: draft.price || "0", currency },
            validity_days: draft.validity_days ? Number(draft.validity_days) : null,
          },
        }),
      ),
    () => setDraft(empty),
  );
  return (
    <div className="space-y-6">
      <QueryState query={packages}>
        <Table
          caption={t("catalogue.tabs.packages")}
          headers={[
            t("catalogue.name"),
            t("catalogue.packages.quantity"),
            t("catalogue.products.price"),
            t("catalogue.packages.validity"),
          ]}
        >
          {(packages.data?.results ?? []).map((p) => (
            <tr key={p.id}>
              <Cell>{p.name}</Cell>
              <Cell>
                {t(`catalogue.packages.amount.${p.quantity_type}`, { count: Number(p.quantity) })}
              </Cell>
              <Cell>{formatRate(p.price, i18n.language)}</Cell>
              <Cell>
                {p.validity_days
                  ? t("catalogue.packages.days", { count: p.validity_days })
                  : (p.valid_until ?? "–")}
              </Cell>
            </tr>
          ))}
        </Table>
      </QueryState>
      {canManage ? (
        <AddForm
          title={t("catalogue.packages.new")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error}
        >
          <TextField
            label={t("catalogue.name")}
            required
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
          <SelectField
            label={t("catalogue.packages.unit")}
            value={draft.quantity_type}
            onChange={(e) =>
              setDraft((d) => ({ ...d, quantity_type: e.target.value as QuantityType }))
            }
            options={(["hours", "lessons", "credit"] as const).map((v) => ({
              value: v,
              label: t(`catalogue.packages.units.${v}`),
            }))}
          />
          <TextField
            label={t("catalogue.packages.quantity")}
            inputMode="decimal"
            required
            value={draft.quantity}
            onChange={(e) => setDraft((d) => ({ ...d, quantity: e.target.value }))}
          />
          <TextField
            label={t("catalogue.products.priceIn", { currency })}
            inputMode="decimal"
            required
            value={draft.price}
            onChange={(e) => setDraft((d) => ({ ...d, price: e.target.value }))}
          />
          <TextField
            label={t("catalogue.packages.validityDays")}
            type="number"
            min={1}
            value={draft.validity_days}
            onChange={(e) => setDraft((d) => ({ ...d, validity_days: e.target.value }))}
          />
        </AddForm>
      ) : null}
    </div>
  );
}
