import { unwrap, type components } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export type Schema = components["schemas"]["WorkflowSchema"];
export type FieldSchema = components["schemas"]["AutomationSchema"];

export function useSchemas() {
  const schema = useQuery({
    queryKey: ["workflow-schema"],
    queryFn: async () => unwrap(await api.GET("/api/v1/workflow-schema")),
    staleTime: 5 * 60_000,
  });
  // Field names and operators, to describe older field checks and offer message variables.
  const fields = useQuery({
    queryKey: ["automation-schema"],
    queryFn: async () => unwrap(await api.GET("/api/v1/automation-schema")),
    staleTime: 5 * 60_000,
  });
  return { schema: schema.data, fields: fields.data };
}

export function eventLabel(schema: Schema, event: string) {
  return schema.starts.events.find((e) => e.event === event)?.label ?? event;
}

/** "3 families", "1 lesson": how many records of a kind (a generic "records" for others). */
export function countOf(
  t: (key: string, options?: Record<string, unknown>) => string,
  recordType: string,
  count: number,
): string {
  return t(`workflows.counts.${recordType}`, {
    count,
    defaultValue: t("workflows.counts.record", { count }),
  });
}
