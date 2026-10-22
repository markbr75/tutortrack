import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { cn, TextField } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";

import { api } from "../api";

export interface OrganisationChoice {
  id: string;
  name: string;
  /** The organisation's subdomain. */
  slug: string;
}

/** Waits until typing pauses before searching. */
function useSettled(value: string, delay = 250): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

/**
 * Finds an organisation by name or subdomain (the console's organisations list) and hands
 * back its ID: a combobox whose options show the name at 500 over the subdomain as a caption.
 * Arrow keys move through the options, Enter chooses, Escape closes.
 */
export function OrganisationPicker({
  label,
  value,
  onChange,
  exclude = [],
  hint,
  className,
  showLabel = false,
  multiple = false,
}: {
  label: string;
  /** The label above the field (in a form panel); otherwise it is the placeholder. */
  showLabel?: boolean;
  /** Each choice is added elsewhere and the field empties for the next one. */
  multiple?: boolean;
  value: OrganisationChoice | null;
  onChange: (organisation: OrganisationChoice | null) => void;
  /** IDs already chosen, left out of the options. */
  exclude?: ReadonlyArray<string>;
  hint?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const listId = useId();
  const [text, setText] = useState(value?.name ?? "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // A choice made elsewhere (or cleared after a submit) shows in the field.
  useEffect(() => setText(value?.name ?? ""), [value]);
  const search = useSettled(text.trim());
  const searching = open && search.length > 0 && !value;
  const found = useQuery({
    queryKey: ["platform", "tenants", "pick", search],
    enabled: searching,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/platform/tenants", {
          params: { query: { search, page_size: 8, ordering: "name" } },
        }),
      ),
  });
  const options: OrganisationChoice[] = (found.data?.results ?? [])
    .filter((row) => !exclude.includes(row.id))
    .map((row) => ({ id: row.id, name: row.name, slug: row.slug }));
  const showList = searching && found.isSuccess;
  const choose = (organisation: OrganisationChoice) => {
    onChange(organisation);
    setText(multiple ? "" : organisation.name);
    setOpen(false);
  };
  const optionId = (index: number) => `${listId}-${index}`;
  return (
    <div className={cn("relative", className)}>
      <TextField
        label={label}
        hideLabel={!showLabel}
        size={showLabel ? "md" : "sm"}
        type="search"
        placeholder={showLabel ? t("followUps.orgPicker.placeholder") : label}
        aria-describedby={hint ? `${listId}-hint` : undefined}
        autoComplete="off"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList && options.length ? optionId(active) : undefined}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setActive(0);
          setOpen(true);
          if (value) onChange(null);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setOpen(true);
            if (options.length) {
              const step = e.key === "ArrowDown" ? 1 : -1;
              setActive((index) => (index + step + options.length) % options.length);
            }
          } else if (e.key === "Enter" && showList && options[active]) {
            e.preventDefault();
            choose(options[active]);
          } else if (e.key === "Escape" && showList) {
            e.preventDefault();
            setOpen(false);
          }
        }}
      />
      <ul
        id={listId}
        role="listbox"
        aria-label={label}
        hidden={!showList}
        className="absolute inset-x-0 z-20 mt-1 max-h-72 overflow-y-auto rounded-lg border border-border bg-surface p-1 text-sm shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)]"
      >
        {options.map((option, index) => (
          <li
            key={option.id}
            id={optionId(index)}
            role="option"
            aria-selected={index === active}
            // Keep focus in the field so the choice lands before blur closes the list.
            onMouseDown={(e) => e.preventDefault()}
            onMouseEnter={() => setActive(index)}
            onClick={() => choose(option)}
            className={cn("cursor-pointer rounded-md px-3 py-1.5", index === active && "bg-muted")}
          >
            <span className="block font-medium">{option.name}</span>
            <span className="block text-xs text-muted-foreground">{option.slug}</span>
          </li>
        ))}
      </ul>
      {showList && !options.length ? (
        <p
          role="status"
          className="absolute inset-x-0 z-20 mt-1 rounded-lg border border-border bg-surface px-4 py-2.5 text-sm text-muted-foreground shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)]"
        >
          {t("followUps.orgPicker.noMatches", { search })}
        </p>
      ) : null}
      {hint ? (
        <p id={`${listId}-hint`} className="mt-1 text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
