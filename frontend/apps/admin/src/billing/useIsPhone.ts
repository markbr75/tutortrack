import { useSyncExternalStore } from "react";

const PHONE = "(max-width: 767px)";

function subscribe(onChange: () => void) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const query = window.matchMedia(PHONE);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** True below 768px, where money tables fold secondary columns into context lines. */
export function useIsPhone(): boolean {
  return useSyncExternalStore(
    subscribe,
    () =>
      typeof window !== "undefined" && window.matchMedia ? window.matchMedia(PHONE).matches : false,
    () => false,
  );
}
