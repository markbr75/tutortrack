import { createI18n, I18nextProvider, useTranslation } from "@tutortrack/i18n";
import { ErrorBoundary, ErrorFallback } from "@tutortrack/ui";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { useState } from "react";

import { createQueryClient } from "./api";
import { createPortalRouter } from "./router";

function Fallback({ reset }: { reset: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="p-8">
      <ErrorFallback title={t("errors.generic")} retryLabel={t("errors.retry")} onRetry={reset} />
    </div>
  );
}

export function App({ queryClient }: { queryClient?: QueryClient }) {
  const [client] = useState(() => queryClient ?? createQueryClient());
  const [i18n] = useState(() => createI18n("en-GB"));
  const [router] = useState(() => createPortalRouter(client));
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={client}>
        <ErrorBoundary fallback={(_e, reset) => <Fallback reset={reset} />}>
          <RouterProvider router={router} />
        </ErrorBoundary>
      </QueryClientProvider>
    </I18nextProvider>
  );
}
