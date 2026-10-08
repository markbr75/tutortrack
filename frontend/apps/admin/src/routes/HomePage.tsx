import { useTranslation } from "@tutortrack/i18n";

import { useFeatures } from "../api";

export function HomePage() {
  const { t } = useTranslation();
  const { data: features = {} } = useFeatures();
  const enabled = Object.entries(features).filter(([, on]) => on);

  return (
    <section>
      <h1 className="text-2xl font-semibold">{t("home.title")}</h1>
      <p className="mt-1 text-muted-foreground">{t("home.subtitle")}</p>
      <h2 className="mt-8 text-lg font-medium">{t("home.features")}</h2>
      {enabled.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">{t("home.noFeatures")}</p>
      ) : (
        <ul className="mt-2 list-disc pl-6 text-sm">
          {enabled.map(([key]) => (
            <li key={key}>{key}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
