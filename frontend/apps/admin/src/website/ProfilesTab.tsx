import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { errorText } from "./helpers";

type Profile = components["schemas"]["PublicProfile"];

/** Public tutor profile moderation (FR-24-5): approve or reject tutors' edits. */
export function ProfilesTab() {
  const { t } = useTranslation();
  const [status, setStatus] = useState("pending");
  const profiles = useQuery({
    queryKey: ["public-profiles", status],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/public-profiles", {
          params: { query: status ? { status } : {} },
        }),
      ),
  });
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("website.profiles.intro")}</p>
      <SelectField
        label={t("website.profiles.show")}
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        options={[
          { value: "pending", label: t("website.profiles.status_pending") },
          { value: "approved", label: t("website.profiles.status_approved") },
          { value: "rejected", label: t("website.profiles.status_rejected") },
          { value: "hidden", label: t("website.profiles.status_hidden") },
          { value: "", label: t("website.profiles.all") },
        ]}
      />
      {!profiles.data ? (
        <Spinner label={t("grid.loading")} />
      ) : profiles.data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("website.profiles.none")}</p>
      ) : (
        <ul className="space-y-3">
          {profiles.data.results.map((p) => (
            <ProfileReview key={p.id} profile={p} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ProfileReview({ profile }: { profile: Profile }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["public-profiles"] });
  const approve = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public-profiles/{id}/approve", {
          params: { path: { id: profile.id } },
        }),
      ),
    onSuccess: refresh,
  });
  const reject = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public-profiles/{id}/reject", {
          params: { path: { id: profile.id } },
          body: { reason },
        }),
      ),
    onSuccess: refresh,
  });
  const hide = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public-profiles/{id}/hide", {
          params: { path: { id: profile.id } },
        }),
      ),
    onSuccess: refresh,
  });
  const draft = profile.draft;
  const live = profile.published;
  const changed = (key: "display_name" | "headline" | "bio") =>
    (draft[key] ?? "") !== (live[key] ?? "");
  return (
    <li className="space-y-2 rounded-lg border border-border p-4">
      <h3 className="font-semibold">
        {profile.tutor_name}{" "}
        <span className="text-sm font-normal text-muted-foreground">
          · {t(`website.profiles.status_${profile.status}`)}
          {profile.submitted_at
            ? ` · ${t("website.profiles.submitted", {
                when: formatDateTime(profile.submitted_at, i18n.language),
              })}`
            : ""}
        </span>
      </h3>
      <dl className="grid gap-2 text-sm sm:grid-cols-[10rem_1fr]">
        {(["display_name", "headline", "bio"] as const).map((key) => (
          <div key={key} className="contents">
            <dt className="font-medium">
              {t(`website.profiles.${key}`)}
              {changed(key) ? (
                <span className="ml-1 rounded bg-warning/15 px-1 text-xs">
                  {t("website.profiles.changed")}
                </span>
              ) : null}
            </dt>
            <dd className="whitespace-pre-wrap">{draft[key] || "—"}</dd>
          </div>
        ))}
      </dl>
      {profile.rejection_reason ? (
        <Alert tone="warning">
          {t("website.profiles.rejectedBecause", { reason: profile.rejection_reason })}
        </Alert>
      ) : null}
      {approve.isError || reject.isError ? (
        <Alert tone="danger">{errorText(approve.error ?? reject.error)}</Alert>
      ) : null}
      <div className="flex flex-wrap items-end gap-2">
        {profile.status !== "approved" ? (
          <Button size="sm" loading={approve.isPending} onClick={() => approve.mutate()}>
            {t("website.profiles.approve")}
          </Button>
        ) : null}
        {profile.status === "pending" ? (
          <>
            <TextField
              label={t("website.profiles.reason")}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <Button
              size="sm"
              variant="secondary"
              disabled={!reason.trim()}
              onClick={() => reject.mutate()}
            >
              {t("website.profiles.reject")}
            </Button>
          </>
        ) : null}
        {profile.listed ? (
          <Button size="sm" variant="ghost" onClick={() => hide.mutate()}>
            {t("website.profiles.hide")}
          </Button>
        ) : null}
      </div>
    </li>
  );
}
