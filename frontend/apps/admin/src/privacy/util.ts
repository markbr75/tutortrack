export const PAGE = { page_size: 200 };

/** Days until (positive) or since (negative) a deadline. */
export function daysUntil(iso: string): number {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
}
