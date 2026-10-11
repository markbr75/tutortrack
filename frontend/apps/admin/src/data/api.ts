import { unwrap, type components } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export type ImportBatch = components["schemas"]["ImportBatch"];
export type ImportPreview = components["schemas"]["ImportPreview"];
export type ImportRow = components["schemas"]["ImportRow"];
export type ImportEntity = components["schemas"]["ImportEntity"];
export type ImportField = components["schemas"]["ImportField"];
export type MigrationProject = components["schemas"]["MigrationProject"];
export type ExportJob = components["schemas"]["ExportJob"];

export interface BatchStats {
  rows?: number;
  valid?: number;
  invalid?: number;
  warnings?: number;
  imported?: number;
  created?: number;
  updated?: number;
  skipped?: number;
  failed?: number;
  reverted?: number;
  kept?: number;
  actions?: Record<string, number>;
  will?: Record<string, Record<string, number>>;
}

export interface StepState {
  status: "pending" | "in_progress" | "done" | "skipped";
  batches?: string[];
  note?: string;
}

export interface ReconciliationLine {
  metric: string;
  source: string;
  imported: string;
  difference: string;
  ok: boolean;
}

/** Imports still being worked on in the background: poll them. */
export const BUSY = new Set(["validating", "importing", "rolling_back"]);

export function statsOf(batch: ImportBatch): BatchStats {
  return (batch.stats ?? {}) as BatchStats;
}

export function useImportCatalogue() {
  return useQuery({
    queryKey: ["imports", "catalogue"],
    queryFn: async () => unwrap(await api.GET("/api/v1/import-catalogue")),
    staleTime: 5 * 60_000,
  });
}

export function useBatch(id: string) {
  return useQuery({
    queryKey: ["imports", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/imports/{id}", { params: { path: { id } } })),
    refetchInterval: (query) =>
      query.state.data && BUSY.has(query.state.data.status) ? 2000 : false,
  });
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Direct-to-storage upload (create → PUT → complete), then wait for the virus scan. */
export async function uploadSpreadsheet(file: File, wait = 1000): Promise<string> {
  const created = unwrap(
    await api.POST("/api/v1/files/uploads", {
      body: {
        filename: file.name,
        content_type: file.type || (file.name.endsWith(".xlsx") ? XLSX : "text/csv"),
        size_bytes: file.size,
        visibility: "private",
      },
    }),
  );
  const put = await fetch(created.upload.url, {
    method: created.upload.method,
    headers: created.upload.headers,
    body: file,
  });
  if (!put.ok) throw new Error("upload failed");
  const id = created.file.id;
  let stored = unwrap(await api.POST("/api/v1/files/{id}/complete", { params: { path: { id } } }));
  for (let attempt = 0; attempt < 30 && stored.scan_status === "pending"; attempt += 1) {
    await sleep(wait);
    stored = unwrap(await api.GET("/api/v1/files/{id}", { params: { path: { id } } }));
  }
  return id;
}

export const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
