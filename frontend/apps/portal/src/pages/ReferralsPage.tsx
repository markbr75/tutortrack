import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Button, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

/** Copy a link to the clipboard, announcing the result to screen readers. */
export function CopyLink({ label, url }: { label: string; url: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-1">
      <p className="text-sm font-medium">{label}</p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="break-all rounded-md bg-muted px-2 py-1 text-sm">{url}</code>
        <Button
          size="sm"
          variant="secondary"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(url);
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
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
  const page = useQuery({
    queryKey: ["portal", "referrals"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/referrals")),
  });
  if (page.isPending) return <Spinner label={t("grid.loading")} />;
  if (!page.data) return <p>{t("referrals.portal.unavailable")}</p>;
  const p = page.data;
  const program = p.program;
  return (
    <section className="space-y-4" aria-labelledby="referrals-title">
      <h1 id="referrals-title" className="text-xl font-semibold">
        {t("referrals.portal.title")}
      </h1>
      {program ? (
        <p>
          {t(
            program.milestone === "lessons"
              ? "referrals.portal.offerLessons"
              : "referrals.portal.offer",
            {
              reward: formatMoney(program.referrer_reward, i18n.language),
              count: program.milestone_lessons,
            },
          )}
          {program.referee_discount_percent
            ? ` ${t("referrals.portal.friendGets", {
                percent: Number(program.referee_discount_percent).toLocaleString(i18n.language),
              })}`
            : ""}
        </p>
      ) : null}
      <CopyLink label={t("referrals.portal.yourLink")} url={p.link} />
      <p className="text-sm">
        {t("referrals.portal.yourCode")} <code>{p.code}</code>
      </p>
      {p.earned.length ? (
        <p>
          {t("referrals.portal.earned", {
            amount: p.earned.map((m) => formatMoney(m, i18n.language)).join(", "),
          })}
        </p>
      ) : null}
      {p.referrals.length ? (
        <table className="w-full text-sm">
          <caption className="mb-2 text-left font-semibold">
            {t("referrals.portal.friends")}
          </caption>
          <thead>
            <tr className="text-left">
              <th scope="col" className="px-2 py-1">
                {t("referrals.portal.friend")}
              </th>
              <th scope="col" className="px-2 py-1">
                {t("referrals.portal.when")}
              </th>
              <th scope="col" className="px-2 py-1">
                {t("referrals.statusLabel")}
              </th>
              <th scope="col" className="px-2 py-1">
                {t("referrals.rewardLabel")}
              </th>
            </tr>
          </thead>
          <tbody>
            {p.referrals.map((r) => (
              <tr key={r.id}>
                <td className="border-t border-border px-2 py-1">{r.name}</td>
                <td className="border-t border-border px-2 py-1">
                  {formatDate(r.created_at, i18n.language)}
                </td>
                <td className="border-t border-border px-2 py-1">
                  {t(`referrals.portal.status.${r.status}`)}
                </td>
                <td className="border-t border-border px-2 py-1">
                  {r.reward ? formatMoney(r.reward, i18n.language) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>{t("referrals.portal.none")}</p>
      )}
      {program?.terms ? <p className="text-xs text-muted-foreground">{program.terms}</p> : null}
    </section>
  );
}
