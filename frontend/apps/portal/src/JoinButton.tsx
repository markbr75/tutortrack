import { useTranslation } from "@tutortrack/i18n";
import { useEffect, useState } from "react";

const DEFAULT_EARLY_MS = 10 * 60_000;

/** The role-specific "Join the lesson" link (E22-T09). It is enabled from `opensAt`
 * (the organisation's join window before the start) until the end; before then a
 * disabled button says when it opens. Re-checks the time every 30 seconds. */
export function JoinButton({
  url,
  start,
  end,
  opensAt,
  className = "",
}: {
  url: string;
  start: string;
  end: string;
  opensAt?: string | null;
  className?: string;
}) {
  const { t, i18n } = useTranslation();
  const [current, setCurrent] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setCurrent(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  if (!url) return null;
  const opens = opensAt
    ? new Date(opensAt).getTime()
    : new Date(start).getTime() - DEFAULT_EARLY_MS;
  if (current > new Date(end).getTime()) return null;
  const style = `rounded-md px-3 py-2 text-sm ${className}`;
  if (current < opens) {
    const time = new Intl.DateTimeFormat(i18n.language, { timeStyle: "short" }).format(opens);
    return (
      <button type="button" disabled className={`${style} border border-border opacity-70`}>
        {t("portal.joinOpensAt", { time })}
      </button>
    );
  }
  return (
    <a className={`${style} bg-primary text-primary-foreground`} href={url} rel="noreferrer">
      {t("portal.join")}
    </a>
  );
}
