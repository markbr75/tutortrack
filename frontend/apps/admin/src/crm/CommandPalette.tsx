import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState } from "react";

import { api } from "../api";

type Hit = components["schemas"]["SearchHit"];

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

/** Global search (⌘K / Ctrl+K): a modal combobox over people the user can see. */
export function CommandPalette() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const term = useDebounced(q.trim(), 200);
  const results = useQuery({
    queryKey: ["search", term],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/search", { params: { query: { q: term } } })),
    enabled: term.length >= 2,
  });
  const hits = term.length >= 2 ? (results.data ?? []) : [];

  const open = () => {
    setQ("");
    setActive(0);
    dialogRef.current?.showModal();
    inputRef.current?.focus();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        open();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = (hit: Hit) => {
    dialogRef.current?.close();
    if (hit.type === "client")
      void navigate({ to: "/clients/$clientId", params: { clientId: hit.id } });
    else if (hit.type === "student")
      void navigate({ to: "/students/$studentId", params: { studentId: hit.id } });
    else if (hit.type === "tutor")
      void navigate({ to: "/tutors/$tutorId", params: { tutorId: hit.id } });
    else if (hit.client_id)
      void navigate({ to: "/clients/$clientId", params: { clientId: hit.client_id } });
  };

  return (
    <>
      <button
        type="button"
        onClick={open}
        className="rounded-md px-2 py-1 text-left text-sm hover:bg-muted"
        aria-keyshortcuts="Control+K Meta+K"
      >
        {t("search.open")} <kbd className="text-xs text-muted-foreground">⌘K</kbd>
      </button>
      <dialog
        ref={dialogRef}
        aria-label={t("search.title")}
        className="mt-24 w-full max-w-lg rounded-lg border border-border bg-background p-0 shadow-lg backdrop:bg-black/40"
      >
        <div className="p-3">
          <input
            ref={inputRef}
            type="search"
            role="combobox"
            aria-expanded={hits.length > 0}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={hits[active] ? `${listId}-${active}` : undefined}
            aria-label={t("search.title")}
            placeholder={t("search.placeholder")}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((i) => Math.min(i + 1, hits.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((i) => Math.max(i - 1, 0));
              } else if (e.key === "Enter" && hits[active]) {
                e.preventDefault();
                go(hits[active]);
              }
            }}
            className="w-full rounded-md border border-border bg-background px-3 py-2"
          />
        </div>
        <ul
          id={listId}
          role="listbox"
          aria-label={t("search.results")}
          className="max-h-80 overflow-y-auto pb-2"
        >
          {hits.map((hit, index) => (
            <li
              key={`${hit.type}-${hit.id}`}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className="cursor-pointer px-4 py-2 aria-selected:bg-muted"
              onMouseEnter={() => setActive(index)}
              onClick={() => go(hit)}
            >
              <span className="font-medium">{hit.title}</span>{" "}
              <span className="text-sm text-muted-foreground">
                {t(`search.type.${hit.type}`)}
                {hit.subtitle ? ` · ${hit.subtitle}` : ""}
              </span>
            </li>
          ))}
        </ul>
        {term.length >= 2 && results.isSuccess && hits.length === 0 ? (
          <p className="px-4 pb-4 text-sm text-muted-foreground" role="status">
            {t("search.none")}
          </p>
        ) : null}
      </dialog>
    </>
  );
}
