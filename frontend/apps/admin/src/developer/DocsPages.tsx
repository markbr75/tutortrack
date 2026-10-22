import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  cn,
  PageHeader,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  Spinner,
  Tabs,
} from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api } from "../api";
import { PanelLoading } from "../billing/moneyUi";
import { codeBlock, DocPanel } from "./DeveloperPages";

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

/**
 * Headers, scopes, fields and paths in the guides' prose, set as code like the other
 * developer tabs. They are API names, so they read the same in every language.
 */
const CODE_TOKENS =
  /(Authorization: Bearer <token>|Idempotency-Key|Webhook-(?:Id|Event|Signature)|X-RateLimit-(?:Limit|Remaining|Reset)|Retry-After|\bDeprecation\b|\bSunset\b|\/api\/v1\/|\b[a-z_]+:(?:read|write)\b|\bpage_size\b|\boccurred_at\b|\bnext\b(?= link)|\bnull\b|\bv1\b(?= value))/g;

function withCode(text: string): ReactNode[] {
  return text.split(CODE_TOKENS).map((part, i) =>
    i % 2 === 1 ? (
      <code key={i} className="rounded-sm bg-muted px-1 font-mono text-xs">
        {part}
      </code>
    ) : (
      part
    ),
  );
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
    <div>
      <PageHeader
        title={t("developer.docs.title")}
        description={t("developer.docs.intro")}
        actions={
          <>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              loading={openapi.isPending}
              onClick={() => openapi.mutate()}
            >
              {t("developer.docs.openapi")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              loading={postman.isPending}
              onClick={() => postman.mutate()}
            >
              {t("developer.docs.postman")}
            </Button>
            <a className={buttonClass({ variant: "secondary", size: "sm" })} href="/api/v1/redoc/">
              {t("developer.docs.reference")}
            </a>
          </>
        }
      />
      <div className="max-w-4xl space-y-6">
        <RuledPanel title={t("developer.docs.quickstart")} flush>
          <Tabs
            label={t("developer.docs.language")}
            className="pt-1 [&>[role=tablist]]:mb-0 [&>[role=tablist]]:px-5 [&>[role=tablist]]:[mask-image:none]"
            tabs={[
              { key: "curl", label: "curl" },
              { key: "python", label: "Python" },
              { key: "js", label: "JavaScript" },
            ]}
            value={lang}
            onChange={setLang}
          >
            <div className="px-5 py-4">
              <pre className={codeBlock} tabIndex={0}>
                {SAMPLES[lang]}
              </pre>
            </div>
          </Tabs>
        </RuledPanel>
        {GUIDES.map((key) => (
          <DocPanel key={key} title={t(`developer.docs.guides.${key}.title`)}>
            <p className="max-w-prose">{withCode(t(`developer.docs.guides.${key}.body`))}</p>
            {key === "webhooks" ? (
              <>
                <pre className={codeBlock} tabIndex={0}>
                  {
                    "Webhook-Signature: t=1760090400,v1=5257a869e7ecebeda32affa62cdca3fa51cad7e77a0e56ff536d0ce8e108d8bd"
                  }
                </pre>
                <h3 className="pt-1 font-medium">Python</h3>
                <pre className={codeBlock} tabIndex={0}>
                  {VERIFY.python}
                </pre>
                <h3 className="pt-1 font-medium">Node.js</h3>
                <pre className={codeBlock} tabIndex={0}>
                  {VERIFY.js}
                </pre>
              </>
            ) : null}
          </DocPanel>
        ))}
        <RuledPanel title={t("developer.docs.changelog")} flush>
          {!changelog.data ? (
            <PanelLoading label={t("grid.loading")} />
          ) : (
            <PanelRows>
              {changelog.data.map((entry) => (
                <PanelRow key={`${entry.released_on}-${entry.title}`}>
                  <p className="font-medium">{entry.title}</p>
                  <p className="text-xs text-muted-foreground">
                    <span className="tabular-nums">
                      {formatDate(entry.released_on, i18n.language)}
                    </span>
                    {" · "}
                    {entry.description}
                  </p>
                </PanelRow>
              ))}
            </PanelRows>
          )}
        </RuledPanel>
      </div>
    </div>
  );
}

/** Settings → Integrations directory (FR-27-5): each category a ruled panel of integrations,
 * each with its status in words and the way to connect or manage it. */
export function MarketplacePage() {
  const { t } = useTranslation();
  const entries = useQuery({
    queryKey: ["marketplace"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/marketplace")),
  });
  const categories = Array.from(new Set((entries.data ?? []).map((e) => e.category)));
  return (
    <div>
      <PageHeader title={t("settingsNav.marketplace")} description={t("marketplace.intro")} />
      <div className="space-y-6">
        {!entries.data ? (
          <RuledPanel label={t("marketplace.title")} flush>
            <PanelLoading label={t("grid.loading")} />
          </RuledPanel>
        ) : null}
        {categories.map((category) => {
          const items = (entries.data ?? []).filter((e) => e.category === category);
          return (
            <RuledPanel
              key={category}
              titleId={`mk-${category}`}
              title={t(`marketplace.categories.${category}`, {
                defaultValue: t(`gapG6.categories.${category}`, { defaultValue: category }),
              })}
              flush
            >
              <PanelRows>
                {items.map((entry) => (
                  <PanelRow
                    key={entry.key}
                    className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
                  >
                    <div className="min-w-0">
                      <p className="font-medium">{entry.name}</p>
                      {/* The status leads the one caption line, so it sits in the same place
                          on every row whatever the width of the button beside it. */}
                      <p className="text-xs text-muted-foreground">
                        <span
                          className={cn(
                            entry.status === "needs_attention" && "font-semibold text-margin",
                            entry.status === "connected" && "font-medium text-foreground",
                          )}
                        >
                          {entry.status === "needs_attention"
                            ? t("gapG6.needsAttention")
                            : t(`marketplace.status.${entry.status}`)}
                        </span>
                        {" · "}
                        {entry.description}
                        {entry.detail ? ` ${entry.detail}` : ""}
                      </p>
                    </div>
                    {entry.settings_path && entry.status !== "coming_soon" ? (
                      <a
                        href={entry.settings_path}
                        className={cn(
                          buttonClass({ variant: "secondary", size: "sm" }),
                          "shrink-0 self-start sm:self-auto sm:whitespace-nowrap",
                        )}
                      >
                        {entry.status === "connected"
                          ? t("marketplace.manage", { name: entry.name })
                          : t("marketplace.connect", { name: entry.name })}
                      </a>
                    ) : null}
                  </PanelRow>
                ))}
              </PanelRows>
            </RuledPanel>
          );
        })}
      </div>
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
      <div className="mx-auto max-w-lg">
        <Alert tone="danger" title={t("oauth.invalidTitle")}>
          {consent.error.message}
        </Alert>
      </div>
    );
  if (!consent.data) return <Spinner label={t("grid.loading")} />;
  const c = consent.data;
  return (
    <div className="mx-auto max-w-lg">
      <PageHeader
        title={t("oauth.title", { app: c.application.name, organisation: c.organisation_name })}
        description={c.application.description || undefined}
      />
      <RuledPanel title={t("oauth.wants")} titleId="oauth-scopes" flush>
        <PanelRows>
          {c.scopes.map((s) => (
            <PanelRow key={s.key}>{s.description}</PanelRow>
          ))}
        </PanelRows>
        <p className="border-t border-rule px-5 py-3 text-xs break-words text-muted-foreground">
          {t("oauth.redirectNotice", { url: c.redirect_uri })}
        </p>
        <PanelFooter>
          <Button
            type="button"
            variant="secondary"
            onClick={() => decide.mutate(false)}
            disabled={decide.isPending}
          >
            {t("oauth.deny")}
          </Button>
          <Button
            type="button"
            onClick={() => decide.mutate(true)}
            loading={decide.isPending && decide.variables === true}
            disabled={decide.isPending}
          >
            {t("oauth.allow")}
          </Button>
        </PanelFooter>
      </RuledPanel>
    </div>
  );
}
