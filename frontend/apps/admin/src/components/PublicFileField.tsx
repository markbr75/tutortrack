import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Spinner } from "@tutortrack/ui";
import { useId, useState } from "react";

import { api } from "../api";

/** Where an anonymous upload goes (G5a): a public form or a job opening, by slug. */
export interface UploadTarget {
  target: "form" | "opening";
  slug: string;
}

type Kind = "cv" | "document" | "video";

const ACCEPT: Record<Kind, string> = {
  cv: ".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  document:
    ".pdf,.doc,.docx,.jpg,.jpeg,.png,.webp,.heic,application/pdf,image/jpeg,image/png,image/webp,image/heic",
  video: ".mp4,.mov,.webm,video/mp4,video/quicktime,video/webm",
};

interface Uploaded {
  token: string;
  filename: string;
}

/** Upload one file for a public form: start → PUT to storage → complete (size, type and
 * signature checked, malware scan queued). Resolves to the token the form sends. */
async function uploadPublicFile(where: UploadTarget, kind: Kind, file: File) {
  const created = unwrap(
    await api.POST("/api/v1/public/uploads", {
      body: {
        target: where.target,
        slug: where.slug,
        kind,
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
      },
    }),
  );
  const put = await fetch(created.upload.url, {
    method: created.upload.method,
    headers: created.upload.headers,
    body: file,
  });
  if (!put.ok) throw new Error("upload failed");
  unwrap(await api.POST("/api/v1/public/uploads/complete", { body: { token: created.token } }));
  return created.token;
}

/** A form's file field on public pages (FR-17-1 enquiry attachments, FR-18-1 CV and video).
 * The answer is the upload token, or a list of tokens when ``multiple``. */
export function PublicFileField({
  label,
  kind,
  multiple,
  required,
  error,
  where,
  onChange,
}: {
  label: string;
  kind: Kind;
  multiple?: boolean;
  required?: boolean;
  error?: string;
  where: UploadTarget;
  onChange: (value: string | string[] | undefined) => void;
}) {
  const { t } = useTranslation();
  const inputId = useId();
  const hintId = useId();
  const [files, setFiles] = useState<Uploaded[]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState("");
  const publish = (next: Uploaded[]) => {
    setFiles(next);
    const tokens = next.map((f) => f.token);
    onChange(multiple ? tokens : tokens[0]);
  };
  const add = async (list: FileList | null) => {
    if (!list?.length) return;
    setBusy(true);
    setFailed("");
    try {
      const added: Uploaded[] = [];
      for (const file of Array.from(list)) {
        added.push({ token: await uploadPublicFile(where, kind, file), filename: file.name });
      }
      publish(multiple ? [...files, ...added].slice(0, 5) : added.slice(0, 1));
    } catch (e) {
      setFailed(
        e instanceof Error && e.message !== "upload failed" ? e.message : t("hiring.upload.failed"),
      );
    } finally {
      setBusy(false);
    }
  };
  const message = failed || error;
  return (
    <fieldset className="space-y-1 text-sm">
      <legend className="font-medium">
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </legend>
      <p id={hintId} className="text-xs text-muted-foreground">
        {t(`hiring.upload.hint.${kind}`)}
      </p>
      {files.length ? (
        <ul className="space-y-1" aria-live="polite">
          {files.map((f) => (
            <li key={f.token} className="flex items-center gap-2">
              <span>{f.filename}</span>
              <button
                type="button"
                className="text-muted-foreground underline underline-offset-2"
                onClick={() => publish(files.filter((x) => x.token !== f.token))}
              >
                {t("hiring.upload.remove", { name: f.filename })}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {multiple || !files.length ? (
        <div className="flex items-center gap-2">
          <label htmlFor={inputId} className="sr-only">
            {label}
          </label>
          <input
            id={inputId}
            type="file"
            accept={ACCEPT[kind]}
            multiple={multiple}
            disabled={busy}
            aria-describedby={hintId}
            aria-invalid={message ? true : undefined}
            className="text-sm"
            onChange={(e) => {
              void add(e.target.files);
              e.target.value = "";
            }}
          />
          {busy ? <Spinner label={t("hiring.upload.uploading")} /> : null}
        </div>
      ) : null}
      {message ? (
        <p className="text-xs text-danger" role="alert">
          {message}
        </p>
      ) : null}
    </fieldset>
  );
}
