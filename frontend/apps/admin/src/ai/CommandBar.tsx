import { Sparkles } from "lucide-react";
import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { api, usePermission } from "../api";
import { useAiFeature } from "./ai";
import { AiError, AiFeedback, AiNotice, ProposalList } from "./AiParts";

type Search = components["schemas"]["AITutorSearch"];

const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

/** Run a tutor search the command bar set up (only after the person asks to). */
function TutorSearch({ search }: { search: Search }) {
  const { t } = useTranslation();
  const run = useMutation({
    mutationFn: async () => {
      const weekday = WEEKDAYS.indexOf(search.weekday);
      return unwrap(
        await api.POST("/api/v1/matching/search", {
          body: {
            subject: search.subject,
            level: search.level,
            mode: search.mode as "online" | "in_person" | "either",
            postcode: search.postcode,
            slots: weekday >= 0 && search.after_time ? [{ weekday, time: search.after_time }] : [],
            include_restricted: false,
            limit: 5,
          },
        }),
      );
    },
  });
  const parts = [
    search.subject_name,
    search.level_name,
    search.weekday ? t(`ai.weekdays.${search.weekday}`) : "",
    search.after_time ? `${search.after_time}–${search.before_time || ""}` : "",
    search.postcode,
    t(`ai.modes.${search.mode}`),
  ].filter(Boolean);
  return (
    <li className="space-y-2 rounded-md border border-border px-3 py-2 text-sm">
      <p>{parts.join(" · ")}</p>
      <Button size="sm" variant="secondary" loading={run.isPending} onClick={() => run.mutate()}>
        {t("ai.command.runSearch")}
      </Button>
      <AiError error={run.error} />
      {run.data ? (
        run.data.results.length ? (
          <ol className="list-decimal pl-5" aria-label={t("ai.command.results")}>
            {run.data.results.map((row) => (
              <li key={row.tutor.id}>
                <Link
                  to="/tutors/$tutorId"
                  params={{ tutorId: row.tutor.id }}
                  className="font-medium text-link underline-offset-2 hover:underline"
                >
                  {row.tutor.name}
                </Link>{" "}
                <span className="text-muted-foreground tabular-nums">({row.score})</span>
              </li>
            ))}
          </ol>
        ) : (
          <p role="status">{t("ai.command.noResults")}</p>
        )
      ) : null}
    </li>
  );
}

/** The AI command bar (FR-31-5, ⌘J / Ctrl+J): a request in plain words becomes proposed
 * changes to confirm, or a tutor search to run. */
export function CommandBar() {
  const { t } = useTranslation();
  const enabled = useAiFeature("command_bar");
  const canSearch = usePermission("matching.search");
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const inputId = useId();
  const [text, setText] = useState("");
  const command = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/ai/command", { body: { text } })),
  });

  const open = () => {
    command.reset();
    dialogRef.current?.showModal();
    inputRef.current?.focus();
  };

  useEffect(() => {
    if (!enabled) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        command.reset();
        dialogRef.current?.showModal();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset is stable
  }, [enabled]);

  if (!enabled) return null;
  const result = command.data;
  return (
    <>
      <button
        type="button"
        onClick={open}
        className="flex h-9 shrink-0 items-center gap-2 rounded-md border border-border bg-surface px-3 text-sm hover:bg-muted"
        aria-keyshortcuts="Control+J Meta+J"
      >
        <Sparkles aria-hidden="true" className="size-4 text-link" strokeWidth={1.75} />
        <span className="max-sm:sr-only">{t("ai.command.open")}</span>
        <kbd className="hidden rounded border border-border px-1.5 text-xs text-muted-foreground lg:inline">
          ⌘J
        </kbd>
      </button>
      <dialog
        ref={dialogRef}
        aria-labelledby={titleId}
        className="mx-auto mt-24 w-[calc(100%-2rem)] max-w-xl rounded-xl border border-border bg-surface p-0 text-foreground shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)] backdrop:bg-black/40"
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-2.5">
          <h2 id={titleId} className="text-base font-semibold">
            {t("ai.command.open")}
          </h2>
          <Button
            size="sm"
            variant="ghost"
            className="-mr-3 text-muted-foreground"
            onClick={() => dialogRef.current?.close()}
          >
            {t("ai.command.close")}
          </Button>
        </div>
        <div className="space-y-3 px-5 py-4">
          <form
            className="flex gap-2"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              if (text.trim()) command.mutate();
            }}
          >
            <label htmlFor={inputId} className="sr-only">
              {t("ai.command.label")}
            </label>
            <input
              id={inputId}
              ref={inputRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t("ai.command.placeholder")}
              className="h-10 w-full rounded-md border border-field bg-surface px-3 text-sm"
            />
            <Button type="submit" loading={command.isPending} disabled={!text.trim()}>
              {t("ai.command.run")}
            </Button>
          </form>
          <div aria-live="polite" className="space-y-3">
            {command.isPending ? <p className="text-sm">{t("ai.command.working")}</p> : null}
            <AiError error={command.error} />
            {result ? (
              <>
                {result.message ? <p className="text-sm">{result.message}</p> : null}
                <ProposalList
                  proposals={result.proposals}
                  onDone={() => void queryClient.invalidateQueries()}
                />
                {result.searches.length && canSearch ? (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold">{t("ai.command.searches")}</h3>
                    <ul className="space-y-2">
                      {result.searches.map((search, i) => (
                        <TutorSearch key={i} search={search} />
                      ))}
                    </ul>
                  </div>
                ) : null}
                {!result.proposals.length && !result.searches.length ? (
                  <p className="text-sm text-muted-foreground">{t("ai.command.empty")}</p>
                ) : null}
                <AiNotice />
                <AiFeedback request={result.request} />
              </>
            ) : null}
          </div>
        </div>
      </dialog>
    </>
  );
}
