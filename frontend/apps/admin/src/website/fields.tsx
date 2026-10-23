import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useId, useState } from "react";

import { isHex } from "./contrast";
import { uploadImage } from "./upload";

/** A colour as a hex value, with the browser's colour picker beside it. */
export function ColourField({
  label,
  value,
  onChange,
  error,
  fallback,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  /** May be left empty: the swatch then shows this colour, and empty isn't invalid. */
  fallback?: string;
}) {
  const empty = fallback !== undefined && value === "";
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-hidden="true"
          tabIndex={-1}
          className="h-10 w-12 cursor-pointer rounded-md border border-border bg-surface p-1"
          value={isHex(value) ? value : empty && isHex(fallback) ? fallback : "#000000"}
          onChange={(e) => onChange(e.target.value)}
        />
        <input
          id={id}
          className="h-10 w-32 rounded-md border border-field bg-surface px-3 text-sm tabular-nums uppercase aria-[invalid=true]:border-danger"
          value={value}
          placeholder={empty ? fallback : undefined}
          aria-invalid={error || (!empty && !isHex(value)) ? true : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** An image uploaded straight to storage, shown beside its file input, with Remove. */
export function ImageField({
  label,
  current,
  onUploaded,
}: {
  label: string;
  current: string | null | undefined;
  onUploaded: (id: string | null) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        {current ? (
          <img
            src={`/api/v1/public/assets/${current}`}
            alt=""
            className="h-10 max-w-32 rounded-md border border-border bg-surface object-contain p-1"
          />
        ) : null}
        <input
          id={id}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/svg+xml,image/x-icon"
          className="max-w-full min-w-0 text-sm file:mr-3 file:h-8 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted"
          disabled={busy}
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setBusy(true);
            setError("");
            try {
              onUploaded(await uploadImage(file));
            } catch {
              setError(t("website.uploadFailed"));
            } finally {
              setBusy(false);
            }
          }}
        />
        {current ? (
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => onUploaded(null)}
          >
            {t("website.remove")}
          </Button>
        ) : null}
      </div>
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
