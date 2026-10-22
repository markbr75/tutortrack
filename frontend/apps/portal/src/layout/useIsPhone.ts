import { useSyncExternalStore } from "react";

const PHONE = "(max-width: 767px)";

/** True below 768px, where tables fold their secondary columns into one caption. */
export function useIsPhone(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia?.(PHONE);
      query?.addEventListener("change", notify);
      return () => query?.removeEventListener("change", notify);
    },
    () => window.matchMedia?.(PHONE).matches ?? false,
    () => false,
  );
}
