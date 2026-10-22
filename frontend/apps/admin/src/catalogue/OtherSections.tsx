import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Button, figureCell, FormPanel, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { useIsPhone } from "../billing/useIsPhone";
import { PAGE, formatRate } from "./format";
import { Faded, MutationError, QueryState, Table } from "./shared";

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
    <FormPanel
      title={title}
      submit={t("catalogue.add")}
      pending={pending}
      onSubmit={onSubmit}
      error={error ? <MutationError error={error} /> : null}
      columns={3}
    >
      {children}
    </FormPanel>
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
  const isPhone = useIsPhone();
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
          loading={rates.isPending}
          count={rates.data?.length}
          empty={t("designS6.catalogue.noTaxRates")}
          columns={[
            { header: t("catalogue.name") },
            { header: t("catalogue.tax.percent"), end: true, width: "w-24" },
            ...(isPhone ? [] : [{ header: t("catalogue.tax.exemptReason") }]),
            { header: t("catalogue.tax.default") },
          ]}
        >
          {(rates.data ?? []).map((rate) => (
            <tr key={rate.id}>
              <td className="font-medium">
                {rate.name}
                {isPhone && rate.exempt_reason ? (
                  <span className="block text-xs font-normal text-muted-foreground">
                    {rate.exempt_reason}
                  </span>
                ) : null}
              </td>
              <td className={figureCell}>{Number(rate.percent)}%</td>
              {isPhone ? null : <td>{rate.exempt_reason}</td>}
              <td className="py-1.5">
                {rate.is_default ? (
                  <span className="inline-block py-1">{t("catalogue.tax.isDefault")}</span>
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
              </td>
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
  const isPhone = useIsPhone();
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
          loading={locations.isPending}
          count={locations.data?.results.length}
          empty={t("designS6.catalogue.noLocations")}
          columns={[
            { header: t("catalogue.name") },
            ...(isPhone ? [] : [{ header: t("catalogue.locations.type") }]),
            { header: t("catalogue.locations.address") },
          ]}
        >
          {(locations.data?.results ?? []).map((l) => (
            <tr key={l.id}>
              <td className="font-medium">
                {l.name}
                {isPhone ? (
                  <span className="block text-xs font-normal text-muted-foreground">
                    {t(`catalogue.locations.types.${l.type ?? "centre"}`)}
                  </span>
                ) : null}
              </td>
              {isPhone ? null : <td>{t(`catalogue.locations.types.${l.type ?? "centre"}`)}</td>}
              <td>
                {l.address ? (
                  [l.address.line1, l.address.city, l.address.postcode].filter(Boolean).join(", ")
                ) : (
                  <Faded>–</Faded>
                )}
              </td>
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
  const isPhone = useIsPhone();
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
          loading={products.isPending}
          count={products.data?.results.length}
          empty={t("designS6.catalogue.noProducts")}
          columns={[
            { header: t("catalogue.name") },
            ...(isPhone ? [] : [{ header: t("catalogue.products.category") }]),
            { header: t("catalogue.products.price"), end: true, width: isPhone ? "w-24" : "w-32" },
            ...(isPhone
              ? []
              : [{ header: t("catalogue.products.tutorShare"), end: true, width: "w-28" }]),
          ]}
        >
          {(products.data?.results ?? []).map((p) => (
            <tr key={p.id}>
              <td className="font-medium">
                {p.name}
                {isPhone ? (
                  <span className="block text-xs font-normal text-muted-foreground tabular-nums">
                    {t(`catalogue.products.categories.${p.category ?? "other"}`)} ·{" "}
                    {t("designS6.catalogue.tutorShareIs", {
                      percent: Number(p.tutor_share_percent ?? 0),
                    })}
                  </span>
                ) : null}
              </td>
              {isPhone ? null : (
                <td>{t(`catalogue.products.categories.${p.category ?? "other"}`)}</td>
              )}
              <td className={figureCell}>{formatRate(p.price, i18n.language)}</td>
              {isPhone ? null : (
                <td className={figureCell}>{Number(p.tutor_share_percent ?? 0)}%</td>
              )}
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
            className="text-right tabular-nums"
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
  const isPhone = useIsPhone();
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
          loading={packages.isPending}
          count={packages.data?.results.length}
          empty={t("designS6.catalogue.noPackages")}
          columns={[
            { header: t("catalogue.name") },
            ...(isPhone
              ? []
              : [{ header: t("catalogue.packages.quantity"), end: true, width: "w-28" }]),
            { header: t("catalogue.products.price"), end: true, width: isPhone ? "w-24" : "w-32" },
            ...(isPhone ? [] : [{ header: t("catalogue.packages.validity") }]),
          ]}
        >
          {(packages.data?.results ?? []).map((p) => (
            <tr key={p.id}>
              <td className="font-medium">
                {p.name}
                {isPhone ? (
                  <span className="block text-xs font-normal text-muted-foreground tabular-nums">
                    {[
                      t(`catalogue.packages.amount.${p.quantity_type}`, {
                        count: Number(p.quantity),
                      }),
                      p.validity_days
                        ? t("catalogue.packages.days", { count: p.validity_days })
                        : p.valid_until
                          ? formatDate(p.valid_until, i18n.language)
                          : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                ) : null}
              </td>
              {isPhone ? null : (
                <td className={figureCell}>
                  {t(`catalogue.packages.amount.${p.quantity_type}`, {
                    count: Number(p.quantity),
                  })}
                </td>
              )}
              <td className={figureCell}>{formatRate(p.price, i18n.language)}</td>
              {isPhone ? null : (
                <td className="tabular-nums">
                  {p.validity_days ? (
                    t("catalogue.packages.days", { count: p.validity_days })
                  ) : p.valid_until ? (
                    formatDate(p.valid_until, i18n.language)
                  ) : (
                    <Faded>–</Faded>
                  )}
                </td>
              )}
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
            className="text-right tabular-nums"
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
