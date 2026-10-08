import { useTranslation } from "@tutortrack/i18n";

export function PortalHome() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto max-w-lg p-6">
      <h1 className="text-2xl font-semibold">{t("app.name")}</h1>
      <p className="mt-2 text-muted-foreground">{t("auth.signInBody")}</p>
    </main>
  );
}
