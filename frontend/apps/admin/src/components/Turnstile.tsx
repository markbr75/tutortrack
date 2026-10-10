import { useEffect } from "react";

declare global {
  interface Window {
    onTurnstileToken?: (token: string) => void;
  }
}

/** Cloudflare Turnstile widget, only when the backend has a site key configured. */
export function Turnstile({
  siteKey,
  onToken,
}: {
  siteKey: string;
  onToken: (token: string) => void;
}) {
  useEffect(() => {
    window.onTurnstileToken = onToken;
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    script.async = true;
    document.head.appendChild(script);
    return () => {
      script.remove();
      delete window.onTurnstileToken;
    };
  }, [onToken]);
  return <div className="cf-turnstile" data-sitekey={siteKey} data-callback="onTurnstileToken" />;
}
