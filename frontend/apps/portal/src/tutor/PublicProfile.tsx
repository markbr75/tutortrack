import { ApiError, unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  PanelFooter,
  RuledPanel,
  Spinner,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, uploadFile } from "../api";
import { FileField, Word } from "../layout/PortalPage";
import { AiBioHelper } from "./AiDrafts";

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
  if (!profile.data || !draft) return <Spinner label={t("grid.loading")} />;
  const errors =
    save.error instanceof ApiError
      ? ((save.error.problem as { errors?: Record<string, string[]> }).errors ?? {})
      : {};
  const p = profile.data;
  return (
    <form
      aria-labelledby="public-profile-h"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({ ...draft, ...(photo !== undefined ? { photo } : {}) });
      }}
    >
      <RuledPanel
        title={t("tutor.publicProfile.title")}
        titleId="public-profile-h"
        description={t("tutor.publicProfile.intro")}
        aside={
          // What waits on the business (approval) is margin red; the rest are words in ink.
          <Word
            tone={p.status === "pending" ? "margin" : p.status === "draft" ? "muted" : "ink"}
            className={p.status === "approved" || p.status === "rejected" ? "font-medium" : ""}
          >
            {t(`tutor.publicProfile.status_${p.status}`)}
          </Word>
        }
        flush
      >
        <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
          {p.status === "rejected" && p.rejection_reason ? (
            <Alert tone="warning" className="sm:col-span-2">
              {t("tutor.publicProfile.rejected", { reason: p.rejection_reason })}
            </Alert>
          ) : null}
          <CheckboxField
            className="sm:col-span-2"
            label={t("tutor.publicProfile.listed")}
            checked={p.listed}
            onChange={(e) => save.mutate({ listed: e.target.checked })}
          />
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
          <div className="space-y-3 sm:col-span-2">
            <TextAreaField
              label={t("tutor.publicProfile.bio")}
              rows={6}
              value={draft.bio}
              error={errors.bio?.join(" ")}
              onChange={(e) => setDraft({ ...draft, bio: e.target.value })}
            />
            <AiBioHelper tutorId={p.tutor} onUse={(bio) => setDraft({ ...draft, bio })} />
          </div>
          <FileField
            label={t("tutor.publicProfile.photo")}
            accept="image/png,image/jpeg,image/webp"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (file) setPhoto(await uploadFile(file));
            }}
          />
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">{t("tutor.publicProfile.show")}</legend>
            {SECTIONS.map((key) => (
              <CheckboxField
                key={key}
                label={t(`tutor.publicProfile.${key}`)}
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
            ))}
          </fieldset>
          {save.isSuccess ? (
            <Alert tone="success" className="sm:col-span-2">
              {save.data?.status === "approved"
                ? t("tutor.publicProfile.published")
                : t("tutor.publicProfile.saved")}
            </Alert>
          ) : null}
        </div>
        <PanelFooter>
          <Button type="submit" variant="secondary" loading={save.isPending}>
            {t("tutor.publicProfile.submit")}
          </Button>
        </PanelFooter>
      </RuledPanel>
    </form>
  );
}
