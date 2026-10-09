import { useTranslation } from "@tutortrack/i18n";
import { CookieBanner } from "@tutortrack/ui";
import type { ReactNode } from "react";

/** Centred card for pages outside the signed-in app (signup, verification, onboarding). */
export function PublicLayout({
  title,
  subtitle,
  children,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <main className="min-h-screen px-4 py-12">
      <div className={wide ? "mx-auto max-w-2xl" : "mx-auto max-w-md"}>
        <p className="mb-8 text-center font-semibold">{t("app.name")}</p>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {subtitle ? <p className="mt-1 text-muted-foreground">{subtitle}</p> : null}
        <div className="mt-6">{children}</div>
      </div>
      <CookieBanner
        labels={{
          title: t("cookies.title"),
          body: t("cookies.body"),
          acceptAll: t("cookies.acceptAll"),
          rejectAll: t("cookies.rejectAll"),
          customise: t("cookies.customise"),
          save: t("cookies.save"),
          analytics: t("cookies.analytics"),
          marketing: t("cookies.marketing"),
          necessary: t("cookies.necessary"),
        }}
      />
    </main>
  );
}
