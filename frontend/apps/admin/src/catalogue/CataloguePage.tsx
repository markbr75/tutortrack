import { useTranslation } from "@tutortrack/i18n";
import { Tabs } from "@tutortrack/ui";
import { useState } from "react";

import {
  LocationsSection,
  PackagesSection,
  ProductsSection,
  TaxRatesSection,
} from "./OtherSections";
import { PriceCheck } from "./PriceCheck";
import { ServicesSection } from "./ServicesSection";
import { SubjectsSection } from "./SubjectsSection";

const TABS = ["services", "subjects", "tax", "locations", "products", "packages", "price"] as const;
type Tab = (typeof TABS)[number];

/** Catalogue and pricing settings (E06-T11). */
export function CataloguePage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("services");
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">{t("catalogue.title")}</h1>
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
        {tab === "products" ? <ProductsSection /> : null}
        {tab === "packages" ? <PackagesSection /> : null}
        {tab === "price" ? <PriceCheck /> : null}
      </Tabs>
    </section>
  );
}
