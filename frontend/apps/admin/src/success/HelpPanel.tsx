import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Button, CheckboxField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, usePermission } from "../api";
import { analyticsConsented, setAnalyticsConsent, track } from "./analytics";
import { GUIDANCE_KEY, useGuidance } from "./guidance";
import { Markdown } from "./Markdown";
import { SupportChat } from "./SupportChat";
import { TOURS } from "./tours";

type Tab = "articles" | "whatsNew" | "tours" | "support" | "privacy";

function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

function Articles() {
  const { t } = useTranslation();
  const route = useRouterState({ select: (s) => s.location.pathname });
  const [q, setQ] = useState("");
  const [slug, setSlug] = useState<string | null>(null);
  const term = useDebounced(q.trim(), 250);
  const list = useQuery({
    queryKey: ["help", "articles", term, route],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/help/articles", { params: { query: { q: term, route } } })),
  });
  const article = useQuery({
    queryKey: ["help", "article", slug],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/help/articles/{slug}", { params: { path: { slug: slug ?? "" } } }),
      ),
    enabled: Boolean(slug),
  });
  if (slug) {
    return (
      <article className="space-y-3">
        <Button
          size="sm"
          variant="ghost"
          className="-ml-3 text-muted-foreground"
          onClick={() => setSlug(null)}
        >
          <ChevronLeft aria-hidden="true" className="size-4" strokeWidth={1.75} />
          {t("help.backToArticles")}
        </Button>
        {article.data ? (
          <>
            <h3 className="text-base font-semibold">{article.data.title}</h3>
            <Markdown source={article.data.body} headingLevel={4} />
          </>
        ) : (
          <Spinner label={t("grid.loading")} />
        )}
      </article>
    );
  }
  const results = list.data ?? [];
  return (
    <div className="space-y-3">
      <TextField
        type="search"
        label={t("help.search")}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <h3 className="text-xs font-semibold text-muted-foreground" aria-live="polite">
        {term ? t("help.results", { count: results.length }) : t("help.forThisPage")}
      </h3>
      {results.length === 0 && !list.isPending ? (
        <p className="text-sm text-muted-foreground">{t("help.noResults")}</p>
      ) : null}
      <ul className="divide-y divide-rule rounded-xl border border-border bg-surface empty:hidden">
        {results.map((a) => (
          <li key={a.slug}>
            <button
              type="button"
              className="w-full px-4 py-2.5 text-left hover:bg-muted/60"
              onClick={() => {
                setSlug(a.slug);
                track("help.article_opened", { article: a.slug });
              }}
            >
              <span className="block text-sm font-medium">{a.title}</span>
              <span className="block text-xs text-muted-foreground">{a.summary}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function WhatsNew() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const entries = useQuery({
    queryKey: ["help", "changelog"],
    queryFn: async () => unwrap(await api.GET("/api/v1/help/changelog")),
  });
  const seen = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/help/changelog/seen")),
    onSuccess: (data) => queryClient.setQueryData(GUIDANCE_KEY, data),
  });
  const { mutate } = seen;
  useEffect(() => {
    if (entries.data) mutate();
  }, [entries.data, mutate]);
  return (
    <ul className="divide-y divide-rule">
      {(entries.data ?? []).map((entry) => (
        <li key={entry.slug} className="space-y-2 py-4 first:pt-0">
          <h3 className="text-base font-semibold">{entry.title}</h3>
          <p className="text-xs text-muted-foreground tabular-nums">
            {formatDate(entry.published_on, i18n.language)}
          </p>
          <Markdown source={entry.body} headingLevel={4} />
        </li>
      ))}
      {entries.isPending ? <Spinner label={t("grid.loading")} /> : null}
    </ul>
  );
}

function Tours({ onStart }: { onStart: (key: string) => void }) {
  const { t } = useTranslation();
  const guidance = useGuidance();
  const done = new Set(guidance.data?.completed_tours ?? []);
  return (
    <ul className="divide-y divide-rule rounded-xl border border-border bg-surface">
      {TOURS.map((tour) => (
        <li key={tour.key} className="flex items-center justify-between gap-2 px-4 py-2.5">
          <span>
            <span className="block text-sm font-medium">{t(`tours.${tour.key}.name`)}</span>
            {done.has(tour.key) ? (
              <span className="text-xs text-muted-foreground">{t("tours.taken")}</span>
            ) : null}
          </span>
          <Button size="sm" variant="secondary" onClick={() => onStart(tour.key)}>
            {done.has(tour.key) ? t("tours.again") : t("tours.start")}
          </Button>
        </li>
      ))}
    </ul>
  );
}

function UsagePrivacy() {
  const { t } = useTranslation();
  const guidance = useGuidance();
  const [on, setOn] = useState(analyticsConsented());
  const allowed = guidance.data?.analytics_allowed ?? false;
  return (
    <div className="space-y-3 text-sm">
      <p>{t("productAnalytics.explain")}</p>
      {allowed ? (
        <CheckboxField
          label={t("productAnalytics.toggle")}
          checked={on}
          onChange={(e) => {
            setAnalyticsConsent(e.target.checked);
            setOn(e.target.checked);
          }}
        />
      ) : (
        <p className="text-muted-foreground">{t("productAnalytics.offForOrganisation")}</p>
      )}
    </div>
  );
}

export interface HelpPanelProps {
  open: boolean;
  onClose: () => void;
  onStartTour: (key: string) => void;
  initialTab?: Tab;
}

/**
 * The help panel (E30 FR-30-5): articles for the current page and search, "What's new",
 * product tours, chat with support and the usage-data choice. A modal side sheet: focus
 * moves into it, Escape closes it and focus returns to the Help button.
 */
export function HelpPanel({ open, onClose, onStartTour, initialTab = "articles" }: HelpPanelProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState<Tab>(initialTab);
  const canChat = usePermission("success.support.chat");
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  useEffect(() => setTab(initialTab), [initialTab, open]);
  const tabs = [
    { key: "articles" as const, label: t("help.tabs.articles") },
    { key: "whatsNew" as const, label: t("help.tabs.whatsNew") },
    { key: "tours" as const, label: t("help.tabs.tours") },
    ...(canChat ? [{ key: "support" as const, label: t("help.tabs.support") }] : []),
    { key: "privacy" as const, label: t("help.tabs.privacy") },
  ];
  return (
    <dialog
      ref={ref}
      aria-labelledby="help-panel-title"
      onClose={onClose}
      onCancel={onClose}
      className="m-0 ml-auto h-full max-h-none w-full max-w-md border-l border-border bg-surface p-0 text-foreground backdrop:bg-black/40"
    >
      {open ? (
        <div className="flex h-full flex-col">
          <header className="flex items-center justify-between border-b border-border px-5 py-2.5">
            <h2 id="help-panel-title" className="text-base font-semibold">
              {t("help.title")}
            </h2>
            <Button
              size="sm"
              variant="ghost"
              className="-mr-3 text-muted-foreground"
              onClick={onClose}
            >
              {t("help.close")}
            </Button>
          </header>
          <div className="flex-1 overflow-y-auto overscroll-contain px-5 py-4">
            {/* The sheet is narrow: its five tabs wrap onto a second line rather than hide
                under the row's fade. */}
            <Tabs
              label={t("help.title")}
              tabs={tabs}
              value={tab}
              onChange={setTab}
              className="[&>[role=tablist]]:flex-wrap [&>[role=tablist]]:gap-y-1 [&>[role=tablist]]:pr-0 [&>[role=tablist]]:[mask-image:none]"
            >
              {tab === "articles" ? <Articles /> : null}
              {tab === "whatsNew" ? <WhatsNew /> : null}
              {tab === "tours" ? <Tours onStart={onStartTour} /> : null}
              {tab === "support" && canChat ? <SupportChat /> : null}
              {tab === "privacy" ? <UsagePrivacy /> : null}
            </Tabs>
          </div>
        </div>
      ) : null}
    </dialog>
  );
}
