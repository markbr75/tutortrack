import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Spinner } from "@tutortrack/ui";
import { useMutation } from "@tanstack/react-query";
import { useEffect } from "react";

import { api } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

export function VerifyEmailPage() {
  const { t } = useTranslation();
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  const verify = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/signup/verify-email", { body: { token } })),
  });
  const { mutate } = verify;
  useEffect(() => {
    if (token) mutate();
  }, [token, mutate]);

  return (
    <PublicLayout title={t("verifyEmail.title")}>
      {verify.isSuccess ? (
        <Alert tone="success">{t("verifyEmail.done")}</Alert>
      ) : verify.isError || !token ? (
        <Alert tone="danger">{t("verifyEmail.failed")}</Alert>
      ) : (
        <p className="flex items-center gap-2" role="status">
          <Spinner className="size-4" /> {t("verifyEmail.checking")}
        </p>
      )}
    </PublicLayout>
  );
}
