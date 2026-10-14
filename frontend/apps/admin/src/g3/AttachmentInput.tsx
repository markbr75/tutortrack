import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";
import { uploadFile } from "../learning/hooks";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** One attached file: its name (from storage) and a download link. Names saved before
 * uploads existed are shown as plain text. */
function AttachedFile({ id }: { id: string }) {
  const { t } = useTranslation();
  const isFile = UUID.test(id);
  const file = useQuery({
    queryKey: ["files", id],
    enabled: isFile,
    queryFn: async () => unwrap(await api.GET("/api/v1/files/{id}", { params: { path: { id } } })),
  });
  const open = async () => {
    const link = unwrap(await api.GET("/api/v1/files/{id}/download", { params: { path: { id } } }));
    window.open(link.url, "_blank", "noopener");
  };
  if (!isFile) return <span>{id}</span>;
  if (!file.data) return <span>{t("grid.loading")}</span>;
  return file.data.is_downloadable ? (
    <button type="button" className="underline underline-offset-2" onClick={() => void open()}>
      {file.data.filename}
    </button>
  ) : (
    <span>
      {file.data.filename} <span className="text-muted-foreground">({t("g3.files.scanning")})</span>
    </span>
  );
}

/** Report attachment field (FR-09-4, gap G3): real uploads (direct to storage, scanned for
 * malware) instead of typed names. The answer holds the stored file ids. */
export function AttachmentInput({
  label,
  hint,
  value,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  value: string[];
  onChange: (value: string[]) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const inputId = useId();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setFailed(false);
    try {
      const ids: string[] = [];
      for (const file of Array.from(files)) ids.push(await uploadFile(file));
      onChange([...value, ...ids]);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <fieldset className="space-y-1">
      <legend className="text-sm font-medium">{label}</legend>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      <ul className="space-y-1 text-sm">
        {value.map((id) => (
          <li key={id} className="flex items-center gap-2">
            <AttachedFile id={id} />
            {!disabled ? (
              <button
                type="button"
                className="text-muted-foreground"
                aria-label={t("g3.files.remove")}
                onClick={() => onChange(value.filter((v) => v !== id))}
              >
                ×
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {!disabled ? (
        <div className="flex items-center gap-2">
          <label htmlFor={inputId} className="text-sm">
            {t("g3.files.add")}
          </label>
          <input
            id={inputId}
            type="file"
            multiple
            disabled={busy}
            className="text-sm"
            onChange={(e) => void upload(e.target.files)}
          />
          {busy ? <Spinner className="size-4" label={t("g3.files.uploading")} /> : null}
        </div>
      ) : null}
      {failed ? <Alert tone="danger">{t("g3.files.failed")}</Alert> : null}
    </fieldset>
  );
}
