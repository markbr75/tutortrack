import { unwrap } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export function useInvoiceTemplates(enabled = true) {
  return useQuery({
    queryKey: ["invoice-templates"],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/invoice-templates")),
  });
}

/** The template choices for a family or a job: "" is the fallback (named by `fallback`). */
export function useTemplateOptions(fallback: string) {
  const templates = useInvoiceTemplates();
  return [
    { value: "", label: fallback },
    ...(templates.data ?? []).map((template) => ({ value: template.id, label: template.name })),
  ];
}

/** The organisation's brand colour, which a template uses when it sets none (shares the app
 * shell's branding query). */
export function useBrandColour(): string {
  const branding = useQuery({
    queryKey: ["public-branding"],
    queryFn: async () => unwrap(await api.GET("/api/v1/public/branding")),
  });
  return branding.data?.primary_colour ?? "#1f2937";
}
