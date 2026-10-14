import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useId, useState } from "react";

/** Click-to-sign (gap batch G2): type your full name and tick that you agree. */
export function SignForm({
  title,
  pending,
  error,
  onSign,
  onCancel,
}: {
  title: string;
  pending: boolean;
  error?: string | null;
  onSign: (fullName: string) => void;
  onCancel?: () => void;
}) {
  const { t } = useTranslation();
  const agreeId = useId();
  const [name, setName] = useState("");
  const [agree, setAgree] = useState(false);
  return (
    <form
      className="mt-3 space-y-3 rounded-md border border-border p-3"
      aria-label={t("esign.signTitle", { title })}
      onSubmit={(e) => {
        e.preventDefault();
        if (agree && name.trim()) onSign(name.trim());
      }}
    >
      <p className="text-sm">{t("esign.intro", { title })}</p>
      <TextField
        label={t("esign.fullName")}
        autoComplete="name"
        required
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <div className="flex items-start gap-2 text-sm">
        <input
          id={agreeId}
          type="checkbox"
          className="mt-1"
          checked={agree}
          onChange={(e) => setAgree(e.target.checked)}
        />
        <label htmlFor={agreeId}>{t("esign.agree", { title })}</label>
      </div>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <div className="flex gap-2">
        <Button type="submit" size="sm" loading={pending} disabled={!agree || !name.trim()}>
          {t("esign.sign")}
        </Button>
        {onCancel ? (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            {t("esign.cancel")}
          </Button>
        ) : null}
      </div>
    </form>
  );
}
