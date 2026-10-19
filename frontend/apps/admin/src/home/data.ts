import { unwrap } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { addDays, startOfDay } from "../calendar/dates";

/** Today's lessons (the viewer's day, as in the calendar), in time order. */
export function useTodaysLessons(now: Date, enabled = true) {
  const day = startOfDay(now);
  return useQuery({
    queryKey: ["home-register", day.toISOString()],
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/lessons", {
          params: {
            query: {
              start: day.toISOString(),
              end: addDays(day, 1).toISOString(),
              ordering: "start",
              page_size: 200,
            },
          },
        }),
      ).results,
  });
}

/**
 * a − b for two decimal strings at the same scale (the API quantises both to the currency's
 * minor unit), done in integer minor units so money never passes through a float.
 */
export function subtractAmounts(a: string, b: string): string {
  const places = Math.max((a.split(".")[1] ?? "").length, (b.split(".")[1] ?? "").length);
  const minor = (s: string) => {
    const [whole, frac = ""] = s.replace("-", "").split(".");
    const value = BigInt(`${whole}${frac.padEnd(places, "0")}`);
    return s.startsWith("-") ? -value : value;
  };
  const diff = minor(a) - minor(b);
  const sign = diff < 0n ? "-" : "";
  const digits = (diff < 0n ? -diff : diff).toString().padStart(places + 1, "0");
  return places
    ? `${sign}${digits.slice(0, -places)}.${digits.slice(-places)}`
    : `${sign}${digits}`;
}
