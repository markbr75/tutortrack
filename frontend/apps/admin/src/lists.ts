import { useInfiniteQuery } from "@tanstack/react-query";

/** The `cursor` parameter from a paginated response's `next` link. */
export function cursorFrom(next: string | null | undefined): string | undefined {
  return next
    ? (new URL(next, window.location.origin).searchParams.get("cursor") ?? undefined)
    : undefined;
}

interface Page<T> {
  results: T[];
  next?: string | null;
}

/** Cursor-paginated list for DataGrid: `rows`, `hasMore`, `loadMore`. */
export function useCursorList<T>(
  key: readonly unknown[],
  fetchPage: (cursor: string | undefined) => Promise<Page<T>>,
) {
  const query = useInfiniteQuery({
    queryKey: key,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  return {
    query,
    rows: query.data?.pages.flatMap((page) => page.results) ?? [],
  };
}
