import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, Tabs } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { Card } from "./DeveloperPages";

const pre = "overflow-x-auto rounded-md bg-muted p-3 text-xs";
const linkClass = "underline underline-offset-2";

const SAMPLES = {
  curl: `curl https://app.tutortrack.app/api/v1/clients \\
  -H "Authorization: Bearer $TUTORTRACK_API_KEY"`,
  python: `import requests

r = requests.get(
    "https://app.tutortrack.app/api/v1/clients",
    headers={"Authorization": f"Bearer {api_key}"},
    params={"page_size": 100},
)
r.raise_for_status()
for client in r.json()["results"]:
    print(client["display_name"])`,
  js: `const res = await fetch("https://app.tutortrack.app/api/v1/clients", {
  headers: { Authorization: \`Bearer \${apiKey}\` },
});
const { results, next } = await res.json();`,
} as const;

const VERIFY = {
  python: `import hashlib, hmac, time

def verify(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = [p.split("=", 1) for p in header.split(",")]
    t = next(int(v) for k, v in parts if k == "t")
    if abs(time.time() - t) > tolerance:
        return False  # outside the replay window
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, v) for k, v in parts if k == "v1")`,
  js: `import { createHmac, timingSafeEqual } from "node:crypto";

export function verify(secret, header, rawBody, tolerance = 300) {
  const parts = header.split(",").map((p) => p.split("="));
  const t = Number(parts.find(([k]) => k === "t")[1]);
  if (Math.abs(Date.now() / 1000 - t) > tolerance) return false;
  const expected = createHmac("sha256", secret).update(\`\${t}.\`).update(rawBody).digest("hex");
  return parts.some(([k, v]) => k === "v1" &&
    timingSafeEqual(Buffer.from(v), Buffer.from(expected)));
}`,
} as const;

type Lang = "curl" | "python" | "js";
type GuideKey =
  "auth" | "pagination" | "errors" | "idempotency" | "webhooks" | "rateLimits" | "versioning";
const GUIDES: GuideKey[] = [
  "auth",
  "pagination",
  "errors",
  "idempotency",
  "webhooks",
  "rateLimits",
  "versioning",
];

function download(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** Developer portal: guides, code samples, the public OpenAPI, Postman and the changelog. */
export function DeveloperDocsPage() {
  const { t, i18n } = useTranslation();
  const [lang, setLang] = useState<Lang>("curl");
  const changelog = useQuery({
    queryKey: ["developer-changelog"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/changelog")),
  });
  const postman = useMutation({
    mutationFn: async () => unwrap(await api.GET("/api/v1/developer/postman.json")),
    onSuccess: (data) => download("tutortrack.postman.json", data),
  });
  const openapi = useMutation({
    mutationFn: async () => unwrap(await api.GET("/api/v1/developer/openapi.json")),
    onSuccess: (data) => download("tutortrack-openapi.json", data),
  });
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("developer.docs.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("developer.docs.intro")}</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="secondary" onClick={() => openapi.mutate()}>
          {t("developer.docs.openapi")}
        </Button>
        <Button type="button" variant="secondary" onClick={() => postman.mutate()}>
          {t("developer.docs.postman")}
        </Button>
        <a className={linkClass} href="/api/v1/redoc/">
          {t("developer.docs.reference")}
        </a>
      </div>
      <Card title={t("developer.docs.quickstart")}>
        <Tabs
          label={t("developer.docs.language")}
          tabs={[
            { key: "curl", label: "curl" },
            { key: "python", label: "Python" },
            { key: "js", label: "JavaScript" },
          ]}
          value={lang}
          onChange={setLang}
        >
          <pre className={pre}>{SAMPLES[lang]}</pre>
        </Tabs>
      </Card>
      {GUIDES.map((key) => (
        <Card key={key} title={t(`developer.docs.guides.${key}.title`)}>
          <p className="text-sm">{t(`developer.docs.guides.${key}.body`)}</p>
          {key === "webhooks" ? (
            <>
              <pre className={pre}>
                Webhook-Signature:
                t=1760090400,v1=5257a869e7ecebeda32affa62cdca3fa51cad7e77a0e56ff536d0ce8e108d8bd
              </pre>
              <h3 className="text-sm font-medium">Python</h3>
              <pre className={pre}>{VERIFY.python}</pre>
              <h3 className="text-sm font-medium">Node.js</h3>
              <pre className={pre}>{VERIFY.js}</pre>
            </>
          ) : null}
        </Card>
      ))}
      <Card title={t("developer.docs.changelog")}>
        {!changelog.data ? (
          <Spinner className="size-5" label={t("grid.loading")} />
        ) : (
          <ul className="space-y-2 text-sm">
            {changelog.data.map((entry) => (
              <li key={`${entry.released_on}-${entry.title}`}>
                <span className="font-medium">{formatDate(entry.released_on, i18n.language)}</span>{" "}
                · {entry.title} — {entry.description}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/** Settings → Integrations marketplace (FR-27-5). */
export function MarketplacePage() {
  const { t } = useTranslation();
  const entries = useQuery({
    queryKey: ["marketplace"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/marketplace")),
  });
  if (!entries.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const categories = Array.from(new Set(entries.data.map((e) => e.category)));
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("marketplace.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("marketplace.intro")}</p>
      {categories.map((category) => (
        <section key={category} aria-labelledby={`mk-${category}`} className="space-y-2">
          <h2 id={`mk-${category}`} className="font-semibold">
            {t(`marketplace.categories.${category}`, { defaultValue: category })}
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {entries.data
              .filter((e) => e.category === category)
              .map((entry) => (
                <li key={entry.key} className="space-y-1 rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{entry.name}</span>
                    <span className="rounded bg-muted px-2 py-0.5 text-xs">
                      {t(`marketplace.status.${entry.status}`)}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground">{entry.description}</p>
                  {entry.settings_path && entry.status !== "coming_soon" ? (
                    <a href={entry.settings_path} className={`${linkClass} text-sm`}>
                      {entry.status === "connected"
                        ? t("marketplace.manage", { name: entry.name })
                        : t("marketplace.connect", { name: entry.name })}
                    </a>
                  ) : null}
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** OAuth consent screen: `/oauth/authorize?client_id=…&redirect_uri=…&scope=…`. */
export function OAuthConsentPage() {
  const { t } = useTranslation();
  const params = new URLSearchParams(window.location.search);
  const request = {
    client_id: params.get("client_id") ?? "",
    redirect_uri: params.get("redirect_uri") ?? "",
    response_type: params.get("response_type") ?? "code",
    scope: params.get("scope") ?? "",
    state: params.get("state") ?? "",
    code_challenge: params.get("code_challenge") ?? "",
    code_challenge_method: params.get("code_challenge_method") ?? "",
  };
  const consent = useQuery({
    queryKey: ["oauth-consent", window.location.search],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/oauth/authorize", {
        params: { query: request },
      });
      if (error || !data) {
        const reason = (error ?? {}) as unknown as { error_description?: string; error?: string };
        throw new Error(reason.error_description || reason.error || "invalid_request");
      }
      return data;
    },
    retry: false,
  });
  const decide = useMutation({
    mutationFn: async (approve: boolean) =>
      unwrap(await api.POST("/api/v1/oauth/authorize", { body: { ...request, approve } })),
    onSuccess: (result) => window.location.assign(result.redirect_to),
  });
  if (consent.error)
    return (
      <Alert tone="danger" title={t("oauth.invalidTitle")}>
        {consent.error.message}
      </Alert>
    );
  if (!consent.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const c = consent.data;
  return (
    <div className="mx-auto max-w-lg space-y-4">
      <h1 className="text-2xl font-semibold">
        {t("oauth.title", { app: c.application.name, organisation: c.organisation_name })}
      </h1>
      {c.application.description ? <p className="text-sm">{c.application.description}</p> : null}
      <section aria-labelledby="oauth-scopes">
        <h2 id="oauth-scopes" className="font-medium">
          {t("oauth.wants")}
        </h2>
        <ul className="list-disc pl-5 text-sm">
          {c.scopes.map((s) => (
            <li key={s.key}>{s.description}</li>
          ))}
        </ul>
      </section>
      <p className="text-xs text-muted-foreground">
        {t("oauth.redirectNotice", { url: c.redirect_uri })}
      </p>
      <div className="flex gap-2">
        <Button type="button" onClick={() => decide.mutate(true)} disabled={decide.isPending}>
          {t("oauth.allow")}
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={() => decide.mutate(false)}
          disabled={decide.isPending}
        >
          {t("oauth.deny")}
        </Button>
      </div>
    </div>
  );
}
