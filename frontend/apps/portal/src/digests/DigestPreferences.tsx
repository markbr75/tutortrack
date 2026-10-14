import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

type Digest = components["schemas"]["DigestPreference"];
const DAYS = [0, 1, 2, 3, 4, 5, 6];

/** The digest emails the signed-in person can get (G4, FR-13-2/7): the tutor's daily
 * agenda, a family's weekly schedule and the daily message digest, each with an on/off
 * switch, the local time and (weekly) the day. */
export function DigestPreferences() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const rows = useQuery({
    queryKey: ["digest-preferences"],
    queryFn: async () => unwrap(await api.GET("/api/v1/digest-preferences/mine")),
  });
  const [draft, setDraft] = useState<Record<string, Digest>>({});
  const save = useMutation({
    mutationFn: async (list: Digest[]) =>
      unwrap(
        await api.PUT("/api/v1/digest-preferences/mine", {
          body: list.map((d) => ({
            kind: d.kind,
            enabled: d.enabled,
            send_time: d.send_time,
            weekday: d.weekday,
          })),
        }),
      ),
    onSuccess: (data) => {
      setDraft({});
      queryClient.setQueryData(["digest-preferences"], data);
    },
  });
  if (!rows.data?.length) return null;
  const current = rows.data.map((row) => draft[row.kind] ?? row);
  const weekday = (day: number) =>
    new Date(Date.UTC(2024, 0, 1 + day)).toLocaleDateString(i18n.language, { weekday: "long" });
  const change = (row: Digest, patch: Partial<Digest>) =>
    setDraft((d) => ({ ...d, [row.kind]: { ...row, ...patch } }));

  return (
    <section aria-labelledby="digests-title" className="space-y-3">
      <h2 id="digests-title" className="font-semibold">
        {t("digests.title")}
      </h2>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(current);
        }}
      >
        {current.map((row) => (
          <fieldset key={row.kind} className="space-y-2 rounded-md border border-border p-3">
            <legend className="px-1 text-sm font-medium">{t(`digests.kind.${row.kind}`)}</legend>
            {!row.org_enabled ? (
              <p className="text-xs text-muted-foreground">{t("digests.notSent")}</p>
            ) : null}
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={row.enabled}
                onChange={(e) => change(row, { enabled: e.target.checked })}
              />
              {t("digests.wantIt")}
            </label>
            <div className="flex flex-wrap items-end gap-3">
              <TextField
                className="w-32"
                type="time"
                label={t("digests.time")}
                value={row.send_time}
                onChange={(e) => change(row, { send_time: e.target.value })}
              />
              {row.weekday !== null && row.weekday !== undefined ? (
                <SelectField
                  label={t("digests.day")}
                  value={String(row.weekday)}
                  onChange={(e) => change(row, { weekday: Number(e.target.value) })}
                  options={DAYS.map((d) => ({ value: String(d), label: weekday(d) }))}
                />
              ) : null}
            </div>
          </fieldset>
        ))}
        <Button type="submit" size="sm" disabled={save.isPending}>
          {t("digests.save")}
        </Button>
        {save.isSuccess ? (
          <p role="status" className="text-xs text-muted-foreground">
            {t("digests.saved")}
          </p>
        ) : null}
        {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
      </form>
    </section>
  );
}
