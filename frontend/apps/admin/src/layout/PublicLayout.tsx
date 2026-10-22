import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { applyBrandTheme, cn, CookieBanner, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";

import { api } from "../api";

/** The organisation whose host this is (E24): name, logo and colour. On the root host there
 * is no organisation, so the request fails and the page carries TutorTrack's own name. */
export function usePublicBranding(enabled = true) {
  const brand = useQuery({
    queryKey: ["public-branding"],
    queryFn: async () => unwrap(await api.GET("/api/v1/public/branding")),
    enabled,
    staleTime: 10 * 60_000,
    retry: false,
  });
  const data = brand.data;
  // The tenant colour reaches primary fills, the caret and selection only (colour, not font).
  useEffect(() => {
    if (data) applyBrandTheme(data);
  }, [data]);
  return brand;
}

/**
 * The line that names who the page is from, ruled off above the title: the tenant's logo (with
 * its dark-scheme version) or its name in ink; TutorTrack's name where there is no tenant, or
 * where the reader is TutorTrack's own customer (`tutortrack`). Never a faded kicker.
 */
export function BrandLine({
  tutortrack = false,
  name,
}: {
  tutortrack?: boolean;
  /** The business's name from the page's own data, while or if the branding can't load. */
  name?: string;
}) {
  const { t } = useTranslation();
  const brand = usePublicBranding(!tutortrack);
  const data = tutortrack ? undefined : brand.data;
  const waiting = !tutortrack && brand.isPending;
  return (
    <div className="mb-5 flex min-h-8 items-center border-b border-border pb-4">
      {waiting ? null : data?.logo_url ? (
        <picture>
          {data.logo_dark_url ? (
            <source srcSet={data.logo_dark_url} media="(prefers-color-scheme: dark)" />
          ) : null}
          <img src={data.logo_url} alt={data.name} className="h-8 w-auto" />
        </picture>
      ) : (
        <p className="text-base font-semibold">{data?.name ?? name ?? t("app.name")}</p>
      )}
    </div>
  );
}

/** The quiet "Powered by TutorTrack" credit at the foot of a tenant's public page. */
export function PoweredBy() {
  const { t } = useTranslation();
  const brand = usePublicBranding();
  if (!brand.data?.show_powered_by) return null;
  return (
    <footer className="px-4 pb-8 text-center text-xs text-muted-foreground">
      {t("designS11.poweredBy")}{" "}
      <a
        className="underline underline-offset-2 hover:text-foreground"
        href="https://tutortrack.app"
        target="_blank"
        rel="noreferrer"
      >
        {t("app.name")}
      </a>
    </footer>
  );
}

/** Names the browser tab after the page and whoever it is from. */
function useDocumentTitle(title: string | undefined, tutortrack: boolean) {
  const { t } = useTranslation();
  const brand = usePublicBranding(!tutortrack);
  const from = (!tutortrack && brand.data?.name) || t("app.name");
  useEffect(() => {
    document.title = title ? `${title} · ${from}` : from;
  }, [title, from]);
}

/**
 * Pages outside the signed-in app: the public pages a family, applicant or referee opens on
 * the organisation's host (white-label: its logo or name, its colour on primary fills, a quiet
 * credit at the foot), and the sign-in, sign-up and onboarding pages. One column up to 32rem
 * (42rem when `wide`) with 16px sides: the brand line, the 26px title, one faded-ink line,
 * then the content.
 */
export function PublicLayout({
  title,
  subtitle,
  children,
  wide = false,
  tutortrack = false,
  loading = false,
}: {
  title?: string;
  subtitle?: ReactNode;
  children?: ReactNode;
  wide?: boolean;
  /** TutorTrack's own name instead of the tenant's (sign-up and onboarding). */
  tutortrack?: boolean;
  /** The page's data is on its way: the brand line and the page loader only. */
  loading?: boolean;
}) {
  const { t } = useTranslation();
  useDocumentTitle(loading ? undefined : title, tutortrack);
  return (
    <div className="flex min-h-dvh flex-col">
      <main
        className={cn("mx-auto w-full flex-1 px-4 py-8 sm:px-6", wide ? "max-w-2xl" : "max-w-lg")}
      >
        <header>
          <BrandLine tutortrack={tutortrack} />
          {loading ? (
            <Spinner label={t("grid.loading")} />
          ) : (
            <>
              <h1 className="text-2xl font-semibold">{title}</h1>
              {subtitle ? <p className="mt-1 text-muted-foreground">{subtitle}</p> : null}
            </>
          )}
        </header>
        {loading ? null : <div className="mt-6">{children}</div>}
      </main>
      {tutortrack ? null : <PoweredBy />}
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
    </div>
  );
}
