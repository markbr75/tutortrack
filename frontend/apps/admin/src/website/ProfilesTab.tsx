import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
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
    <div className="max-w-4xl space-y-4">
      <p className="text-sm text-muted-foreground">{t("website.profiles.intro")}</p>
      <div
        className="flex flex-wrap items-center gap-2"
        role="search"
        aria-label={t("website.tabs.profiles")}
      >
        <SelectField
          label={t("website.profiles.show")}
          hideLabel
          size="sm"
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
      </div>
      {!profiles.data ? (
        <Spinner label={t("grid.loading")} />
      ) : profiles.data.results.length === 0 ? (
        <p className="rounded-xl border border-border bg-surface px-5 py-6 text-sm text-muted-foreground">
          {t("website.profiles.none")}
        </p>
      ) : (
        <ul className="space-y-6">
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
    <li>
      <RuledPanel
        title={profile.tutor_name}
        level={3}
        description={
          <>
            <span
              className={profile.status === "pending" ? "font-semibold text-margin" : undefined}
            >
              {t(`website.profiles.status_${profile.status}`)}
            </span>
            {profile.submitted_at ? (
              <span className="tabular-nums">
                {" · "}
                {t("website.profiles.submitted", {
                  when: formatDateTime(profile.submitted_at, i18n.language),
                })}
              </span>
            ) : null}
          </>
        }
        flush
      >
        <dl className="divide-y divide-rule text-sm">
          {(["display_name", "headline", "bio"] as const).map((key) => (
            <div
              key={key}
              className="grid grid-cols-[minmax(6rem,30%)_minmax(0,1fr)] gap-x-4 px-5 py-2.5"
            >
              <dt className="text-muted-foreground">
                {t(`website.profiles.${key}`)}
                {changed(key) ? (
                  <span className="block text-xs font-semibold text-margin">
                    {t("website.profiles.changed")}
                  </span>
                ) : null}
              </dt>
              <dd className="min-w-0 break-words whitespace-pre-wrap">
                {draft[key] || <span className="text-muted-foreground">–</span>}
              </dd>
            </div>
          ))}
        </dl>
        {profile.rejection_reason || approve.isError || reject.isError ? (
          <div className="space-y-2 border-t border-rule px-5 py-4">
            {profile.rejection_reason ? (
              <Alert tone="warning">
                {t("website.profiles.rejectedBecause", { reason: profile.rejection_reason })}
              </Alert>
            ) : null}
            {approve.isError || reject.isError ? (
              <Alert tone="danger">{errorText(approve.error ?? reject.error)}</Alert>
            ) : null}
          </div>
        ) : null}
        <PanelFooter className="items-end">
          {profile.status === "pending" ? (
            <>
              <div className="min-w-56 flex-1 sm:max-w-sm">
                <TextField
                  label={t("website.profiles.reason")}
                  size="sm"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </div>
              <Button
                size="sm"
                variant="secondary"
                className="h-9"
                disabled={!reason.trim()}
                onClick={() => reject.mutate()}
              >
                {t("website.profiles.reject")}
              </Button>
            </>
          ) : null}
          {profile.status !== "approved" ? (
            <Button
              size="sm"
              className="h-9"
              loading={approve.isPending}
              onClick={() => approve.mutate()}
            >
              {t("website.profiles.approve")}
            </Button>
          ) : null}
          {profile.listed ? (
            <Button
              size="sm"
              variant="ghost"
              className="h-9 text-muted-foreground"
              onClick={() => hide.mutate()}
            >
              {t("website.profiles.hide")}
            </Button>
          ) : null}
        </PanelFooter>
      </RuledPanel>
    </li>
  );
}
