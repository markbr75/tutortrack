import { ApiError, unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";

import { api, uploadFile } from "../api";

const SECTIONS = ["qualifications", "languages", "experience", "location"] as const;

interface Draft {
  display_name: string;
  headline: string;
  bio: string;
  show: string[];
}

/** The tutor's public directory profile (E24 FR-24-5): edits wait for approval when the
 * organisation requires it; contact details and links are refused. */
export function PublicProfileSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const bioId = useId();
  const photoId = useId();
  const profile = useQuery({
    queryKey: ["public-profile-mine"],
    queryFn: async () => unwrap(await api.GET("/api/v1/public-profiles/mine")),
    retry: false,
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [photo, setPhoto] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    if (profile.data) {
      const d = profile.data.draft;
      setDraft({
        display_name: d.display_name ?? "",
        headline: d.headline ?? "",
        bio: d.bio ?? "",
        show: [...(d.show ?? [])],
      });
    }
  }, [profile.data]);
  const save = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      unwrap(await api.PUT("/api/v1/public-profiles/mine", { body: body as never })),
    onSuccess: (data) => queryClient.setQueryData(["public-profile-mine"], data),
  });
  if (profile.isError) return null; // not a tutor login with directory access
  if (!profile.data || !draft) return <Spinner className="size-5" label={t("grid.loading")} />;
  const errors =
    save.error instanceof ApiError
      ? ((save.error.problem as { errors?: Record<string, string[]> }).errors ?? {})
      : {};
  const p = profile.data;
  return (
    <section aria-labelledby="public-profile-h" className="space-y-3">
      <h2 id="public-profile-h" className="text-lg font-semibold">
        {t("tutor.publicProfile.title")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("tutor.publicProfile.intro")}</p>
      <p className="text-sm">
        <strong>{t(`tutor.publicProfile.status_${p.status}`)}</strong>
      </p>
      {p.status === "rejected" && p.rejection_reason ? (
        <Alert tone="warning">
          {t("tutor.publicProfile.rejected", { reason: p.rejection_reason })}
        </Alert>
      ) : null}
      <form
        className="space-y-3"
        aria-labelledby="public-profile-h"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ ...draft, ...(photo !== undefined ? { photo } : {}) });
        }}
      >
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={p.listed}
            onChange={(e) => save.mutate({ listed: e.target.checked })}
          />
          {t("tutor.publicProfile.listed")}
        </label>
        <TextField
          label={t("tutor.publicProfile.displayName")}
          value={draft.display_name}
          required
          error={errors.display_name?.[0]}
          onChange={(e) => setDraft({ ...draft, display_name: e.target.value })}
        />
        <TextField
          label={t("tutor.publicProfile.headline")}
          value={draft.headline}
          error={errors.headline?.[0]}
          onChange={(e) => setDraft({ ...draft, headline: e.target.value })}
        />
        <div className="space-y-1">
          <label htmlFor={bioId} className="text-sm font-medium">
            {t("tutor.publicProfile.bio")}
          </label>
          <textarea
            id={bioId}
            rows={6}
            className="w-full rounded-md border border-border bg-background px-3 py-2"
            value={draft.bio}
            aria-invalid={errors.bio ? true : undefined}
            aria-describedby={errors.bio ? `${bioId}-error` : undefined}
            onChange={(e) => setDraft({ ...draft, bio: e.target.value })}
          />
          {errors.bio ? (
            <p id={`${bioId}-error`} role="alert" className="text-sm text-danger">
              {errors.bio.join(" ")}
            </p>
          ) : null}
        </div>
        <div className="space-y-1">
          <label htmlFor={photoId} className="text-sm font-medium">
            {t("tutor.publicProfile.photo")}
          </label>
          <input
            id={photoId}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="text-sm"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (file) setPhoto(await uploadFile(file));
            }}
          />
        </div>
        <fieldset className="space-y-1">
          <legend className="text-sm font-medium">{t("tutor.publicProfile.show")}</legend>
          {SECTIONS.map((key) => (
            <label key={key} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={draft.show.includes(key)}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    show: e.target.checked
                      ? [...draft.show, key]
                      : draft.show.filter((s) => s !== key),
                  })
                }
              />
              {t(`tutor.publicProfile.${key}`)}
            </label>
          ))}
        </fieldset>
        {save.isSuccess ? (
          <Alert tone="success">
            {save.data?.status === "approved"
              ? t("tutor.publicProfile.published")
              : t("tutor.publicProfile.saved")}
          </Alert>
        ) : null}
        <Button type="submit" loading={save.isPending}>
          {t("tutor.publicProfile.submit")}
        </Button>
      </form>
    </section>
  );
}
