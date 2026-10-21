import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";

import { api } from "../api";

export interface AttachedFile {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  is_downloadable: boolean;
}

/** Files uploaded with a record (G5a: enquiry attachments, applicants' CVs and videos). Each
 * opens through a short-lived link once the malware scan has passed. */
export function AttachedFiles({ files, label }: { files?: AttachedFile[]; label?: string }) {
  const { t } = useTranslation();
  if (!files?.length) return null;
  const open = async (id: string) => {
    const link = unwrap(await api.GET("/api/v1/files/{id}/download", { params: { path: { id } } }));
    window.open(link.url, "_blank", "noopener");
  };
  return (
    <div className="space-y-1">
      {label ? <p className="font-medium">{label}</p> : null}
      <ul className="space-y-1">
        {files.map((f) => (
          <li key={f.id}>
            {f.is_downloadable ? (
              <button
                type="button"
                className="font-medium text-link underline-offset-2 hover:underline"
                onClick={() => void open(f.id)}
              >
                {f.filename}
              </button>
            ) : (
              <span>
                {f.filename}{" "}
                <span className="text-xs text-muted-foreground">
                  ({t("hiring.files.scanning")})
                </span>
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
