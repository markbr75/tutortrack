import { useTranslation } from "@tutortrack/i18n";
import { Link } from "@tanstack/react-router";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <section className="text-center">
      <h1 className="text-2xl font-semibold">{t("errors.notFound")}</h1>
      <Link to="/" className="mt-4 inline-block text-brand underline">
        {t("nav.home")}
      </Link>
    </section>
  );
}
