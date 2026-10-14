import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

const STREAM_URL = "/api/v1/notifications/stream";
const RETRY_AFTER_MS = 60_000;

/** Realtime bell updates over Server-Sent Events (G4, FR-13-8).
 *
 * Returns whether the stream is live. While it is, new or read notifications refresh the
 * bell straight away; when the browser has no EventSource, or the stream fails (the server
 * isn't running ASGI, a proxy closes it, Redis is down), the bell keeps its 30-second
 * poll and the stream is tried again a minute later. */
export function useNotificationStream(): boolean {
  const queryClient = useQueryClient();
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.EventSource === "undefined") return;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const refresh = () => void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    const connect = () => {
      if (stopped) return;
      source = new window.EventSource(STREAM_URL, { withCredentials: true });
      source.addEventListener("ready", () => setLive(true));
      source.addEventListener("notification", refresh);
      source.addEventListener("read", refresh);
      source.addEventListener("unavailable", () => fail());
      source.onerror = () => {
        // CONNECTING: the stream ended normally and the browser reconnects by itself.
        if (source?.readyState === window.EventSource.CLOSED) fail();
      };
    };
    const fail = () => {
      source?.close();
      source = null;
      setLive(false);
      retry = setTimeout(connect, RETRY_AFTER_MS);
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      source?.close();
    };
  }, [queryClient]);

  return live;
}
