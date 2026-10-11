import { unwrap } from "@tutortrack/api-client";
import { applyBrandTheme } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { api } from "./api";

/** The organisation's brand for the portal (E24 FR-24-1): colours, font, favicon, the PWA
 * manifest (app name and icon) and whether to show "Powered by TutorTrack". */
export function usePortalBranding() {
  const brand = useQuery({
    queryKey: ["public-branding"],
    queryFn: async () => unwrap(await api.GET("/api/v1/public/branding")),
    staleTime: 10 * 60_000,
    retry: false,
  });
  useEffect(() => {
    if (!brand.data) return;
    applyBrandTheme(brand.data, { full: true });
    document.title = brand.data.app_name || brand.data.name;
    if (!document.querySelector("link[rel=manifest]")) {
      const link = document.createElement("link");
      link.rel = "manifest";
      link.href = "/api/v1/public/manifest";
      document.head.append(link);
    }
  }, [brand.data]);
  return brand.data;
}
