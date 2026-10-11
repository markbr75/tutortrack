import { useTranslation } from "@tutortrack/i18n";

import { usePortalBranding } from "./useBranding";

/** Logo (or the name in the AA-safe brand colour) for the portal header. */
export function BrandMark({ fallback }: { fallback: string }) {
  const brand = usePortalBranding();
  if (brand?.logo_url) {
    return <img src={brand.logo_url} alt={brand.name} className="h-8 w-auto" />;
  }
  return (
    <span className="font-semibold" style={brand ? { color: brand.link_colour } : undefined}>
      {fallback}
    </span>
  );
}

export function PoweredBy() {
  const { t } = useTranslation();
  const brand = usePortalBranding();
  if (!brand?.show_powered_by) return null;
  return (
    <p className="p-4 text-center text-xs text-muted-foreground">
      {t("portal.poweredBy")}{" "}
      <a className="underline" href="https://tutortrack.app" target="_blank" rel="noreferrer">
        TutorTrack
      </a>
    </p>
  );
}
