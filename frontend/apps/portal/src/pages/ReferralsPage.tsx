import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, figureCell, RuledPanel, RuledTable, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { PortalHeader } from "../layout/PortalPage";
import { useIsPhone } from "../layout/useIsPhone";

/** Copy a link to the clipboard, announcing the result to screen readers. */
export function CopyLink({ label, url }: { label: string; url: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-1.5">
      <p className="text-sm font-medium">{label}</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
        <p
          title={url}
          className="min-w-0 flex-1 truncate rounded-md border border-field bg-background px-3 py-2 text-sm"
        >
          {url}
        </p>
        <Button
          variant="secondary"
          className="shrink-0 max-sm:w-full sm:h-auto"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(url);
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? (
            <Check aria-hidden="true" className="size-4" />
          ) : (
            <Copy aria-hidden="true" className="size-4" />
          )}
          {t("referrals.portal.copy")}
        </Button>
      </div>
      <p role="status" className="text-xs text-muted-foreground">
        {copied ? t("referrals.portal.copied") : ""}
      </p>
    </div>
  );
}

/** FR-25-2: the family's referral link, what friends get, and rewards so far. */
export function ReferralsPage() {
  const { t, i18n } = useTranslation();
  const phone = useIsPhone();
  const page = useQuery({
    queryKey: ["portal", "referrals"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/referrals")),
  });
  if (page.isPending) return <Spinner label={t("grid.loading")} />;
  if (!page.data) return <Alert>{t("referrals.portal.unavailable")}</Alert>;
  const p = page.data;
  const program = p.program;
  const when = (iso: string) => formatDate(iso, i18n.language);
  return (
    <div>
      <PortalHeader
        title={t("referrals.portal.title")}
        description={
          program
            ? `${t(
                program.milestone === "lessons"
                  ? "referrals.portal.offerLessons"
                  : "referrals.portal.offer",
                {
                  reward: formatMoney(program.referrer_reward, i18n.language),
                  count: program.milestone_lessons,
                },
              )}${
                program.referee_discount_percent
                  ? ` ${t("referrals.portal.friendGets", {
                      percent: Number(program.referee_discount_percent).toLocaleString(
                        i18n.language,
                      ),
                    })}`
                  : ""
              }`
            : undefined
        }
      />
      <div className="space-y-6">
        <RuledPanel label={t("referrals.portal.yourLink")}>
          <div className="space-y-2">
            <CopyLink label={t("referrals.portal.yourLink")} url={p.link} />
            <p className="text-sm text-muted-foreground">
              {t("referrals.portal.yourCode")}{" "}
              <code className="rounded bg-muted px-1 font-mono text-xs text-foreground">
                {p.code}
              </code>
            </p>
          </div>
        </RuledPanel>
        {p.earned.length ? (
          <p className="border-y border-border py-3 font-semibold tabular-nums">
            {t("referrals.portal.earned", {
              amount: p.earned.map((m) => formatMoney(m, i18n.language)).join(", "),
            })}
          </p>
        ) : null}
        <RuledTable
          framed
          caption={t("referrals.portal.friends")}
          columns={[
            { key: "friend", header: t("referrals.portal.friend") },
            ...(phone ? [] : [{ key: "when", header: t("referrals.portal.when") }]),
            { key: "status", header: t("referrals.statusLabel") },
            { key: "reward", header: t("referrals.rewardLabel"), end: true, width: "w-28" },
          ]}
          empty={p.referrals.length ? undefined : t("referrals.portal.none")}
        >
          {p.referrals.map((r) => (
            <tr key={r.id}>
              <td>
                <span className="font-medium">{r.name}</span>
                {phone ? (
                  <span className="block text-xs text-muted-foreground tabular-nums">
                    {when(r.created_at)}
                  </span>
                ) : null}
              </td>
              {phone ? null : <td className="tabular-nums">{when(r.created_at)}</td>}
              <td>{t(`referrals.portal.status.${r.status}`)}</td>
              <td className={figureCell}>
                {r.reward ? (
                  formatMoney(r.reward, i18n.language)
                ) : (
                  <span className="text-muted-foreground">–</span>
                )}
              </td>
            </tr>
          ))}
        </RuledTable>
        {program?.terms ? <p className="text-xs text-muted-foreground">{program.terms}</p> : null}
      </div>
    </div>
  );
}
