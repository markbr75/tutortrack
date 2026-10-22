import { useTranslation } from "@tutortrack/i18n";
import { Button, buttonClass } from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { flushNow, useOnline, useOutbox } from "./client";
import { discard, retryItem } from "./outbox";

/** Offline and sync status for the tutor (E16-T08): offline banner, changes waiting to
 * sync, and changes the server refused ("your changes need review"). Text, not colour
 * alone, carries the state; updates are announced politely. */
export function OfflineIndicator() {
  const { t } = useTranslation();
  const online = useOnline();
  const items = useOutbox();
  const [syncing, setSyncing] = useState(false);
  const pending = items.filter((i) => i.state === "pending");
  const auth = items.filter((i) => i.state === "auth");
  const review = items.filter((i) => i.state === "review");

  const syncNow = async () => {
    setSyncing(true);
    try {
      await flushNow();
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div aria-live="polite" role="status" aria-label={t("pwa.syncStatus")}>
      {!online ? (
        <p className="border-b border-warning/40 bg-warning/10 px-4 py-2 text-sm">
          <span className="font-semibold">{t("pwa.offline")}</span> {t("pwa.offlineTutor")}
        </p>
      ) : null}
      {pending.length || auth.length ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface px-4 py-2 text-sm">
          <p>
            {auth.length
              ? t("pwa.signInToSync", { count: auth.length + pending.length })
              : t("pwa.waiting", { count: pending.length })}
          </p>
          {online && !auth.length ? (
            <Button size="sm" variant="secondary" onClick={() => void syncNow()} loading={syncing}>
              {t("pwa.syncNow")}
            </Button>
          ) : null}
          {auth.length ? (
            <a
              className="font-medium text-link underline-offset-2 hover:underline"
              href="/portal/"
            >
              {t("pwa.signIn")}
            </a>
          ) : null}
        </div>
      ) : null}
      {review.length ? (
        <section
          aria-labelledby="needs-review"
          className="space-y-2 border-b border-warning/40 bg-warning/10 px-4 py-3 text-sm"
        >
          <h2 id="needs-review" className="font-semibold">
            {t("pwa.needsReview", { count: review.length })}
          </h2>
          <ul className="space-y-2">
            {review.map((item) => (
              <li key={item.id} className="space-y-1">
                <p>
                  <span className="font-medium">
                    {t(item.kind === "lesson.complete" ? "pwa.kind.complete" : "pwa.kind.report", {
                      title: item.label,
                    })}
                  </span>
                  {item.problem ? ` ${t("pwa.because", { reason: item.problem })}` : null}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Link
                    to="/tutor/lessons/$lessonId"
                    params={{ lessonId: item.lessonId }}
                    className={buttonClass({ variant: "secondary", size: "sm" })}
                  >
                    {t("pwa.openLesson")}
                    <span className="sr-only"> {item.label}</span>
                  </Link>
                  <Button size="sm" variant="secondary" onClick={() => void retryItem(item.id)}>
                    {t("pwa.tryAgain")}
                    <span className="sr-only"> {item.label}</span>
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void discard(item.id)}>
                    {t("pwa.discard")}
                    <span className="sr-only"> {item.label}</span>
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

/** Families: the portal needs a connection; say so instead of failing silently. */
export function OfflineBanner() {
  const { t } = useTranslation();
  const online = useOnline();
  return (
    <div aria-live="polite" role="status">
      {!online ? (
        <p className="border-b border-warning/40 bg-warning/10 px-4 py-2 text-sm">
          <span className="font-semibold">{t("pwa.offline")}</span> {t("pwa.offlineFamily")}
        </p>
      ) : null}
    </div>
  );
}
