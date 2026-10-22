import { useTranslation } from "@tutortrack/i18n";
import { PageHeader, Tabs } from "@tutortrack/ui";
import { useState } from "react";

import {
  LocationsSection,
  PackagesSection,
  ProductsSection,
  TaxRatesSection,
} from "./OtherSections";
import { PriceCheck } from "./PriceCheck";
import {
  DiscountsSection,
  PayTiersSection,
  PremiumsSection,
  PriceListsSection,
  RoomsSection,
} from "./PricingSections";
import { ServicesSection } from "./ServicesSection";
import { SubjectsSection } from "./SubjectsSection";

const TABS = [
  "services",
  "subjects",
  "tax",
  "locations",
  "rooms",
  "tiers",
  "premiums",
  "discounts",
  "priceLists",
  "products",
  "packages",
  "price",
] as const;
type Tab = (typeof TABS)[number];

/** Catalogue and pricing settings (E06-T11; Phase 2 tabs from T07-T10). */
export function CataloguePage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("services");
  return (
    <section>
      <PageHeader title={t("catalogue.title")} />
      <Tabs
        label={t("catalogue.title")}
        tabs={TABS.map((key) => ({ key, label: t(`catalogue.tabs.${key}`) }))}
        value={tab}
        onChange={setTab}
      >
        {tab === "services" ? <ServicesSection /> : null}
        {tab === "subjects" ? <SubjectsSection /> : null}
        {tab === "tax" ? <TaxRatesSection /> : null}
        {tab === "locations" ? <LocationsSection /> : null}
        {tab === "rooms" ? <RoomsSection /> : null}
        {tab === "tiers" ? <PayTiersSection /> : null}
        {tab === "premiums" ? <PremiumsSection /> : null}
        {tab === "discounts" ? <DiscountsSection /> : null}
        {tab === "priceLists" ? <PriceListsSection /> : null}
        {tab === "products" ? <ProductsSection /> : null}
        {tab === "packages" ? <PackagesSection /> : null}
        {tab === "price" ? <PriceCheck /> : null}
      </Tabs>
    </section>
  );
}
