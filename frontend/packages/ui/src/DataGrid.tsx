import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type VisibilityState,
} from "@tanstack/react-table";
import { useState } from "react";

import { Button, Spinner } from "./Button";
import { cn } from "./cn";

export interface DataGridLabels {
  loading: string;
  empty: string;
  loadMore: string;
}

export interface DataGridProps<Row> {
  /** Rows already fetched (server-side pagination: pages are appended). */
  rows: Row[];
  columns: ColumnDef<Row, unknown>[];
  getRowId: (row: Row) => string;
  labels: DataGridLabels;
  caption?: string;
  isLoading?: boolean;
  /** Cursor pagination: show "Load more" when the API returned a `next` cursor. */
  hasMore?: boolean;
  isFetchingMore?: boolean;
  onLoadMore?: () => void;
  onRowClick?: (row: Row) => void;
  initialColumnVisibility?: VisibilityState;
  className?: string;
}

/**
 * Data grid used by every list screen. Pagination, filtering and sorting happen on the
 * server (cursor pagination), so the grid only renders what it is given. Saved views and the
 * column chooser (E05) build on `initialColumnVisibility`.
 */
export function DataGrid<Row>({
  rows,
  columns,
  getRowId,
  labels,
  caption,
  isLoading = false,
  hasMore = false,
  isFetchingMore = false,
  onLoadMore,
  onRowClick,
  initialColumnVisibility,
  className,
}: DataGridProps<Row>) {
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    initialColumnVisibility ?? {},
  );
  const table = useReactTable({
    data: rows,
    columns,
    getRowId,
    state: { columnVisibility },
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
  });

  return (
    // Wide tables scroll sideways on small screens; a labelled, focusable region lets
    // keyboard users scroll it too (WCAG 2.1.1).
    <div
      role={caption ? "region" : undefined}
      aria-label={caption}
      tabIndex={caption ? 0 : undefined}
      className={cn("overflow-x-auto rounded-xl border border-border bg-surface", className)}
    >
      <table className="w-full text-left text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="border-b border-border">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th
                  key={header.id}
                  scope="col"
                  className="px-4 py-2.5 text-xs font-semibold whitespace-nowrap text-muted-foreground"
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {isLoading &&
            // Skeleton rows hold the table's shape; the status is announced once.
            [0, 1, 2].map((i) => (
              <tr key={`loading-${i}`} className="border-t border-rule first:border-0">
                <td colSpan={columns.length} className="px-4 py-3">
                  {i === 0 ? <Spinner className="sr-only" label={labels.loading} /> : null}
                  <div aria-hidden="true" className="h-4 animate-pulse rounded bg-muted" />
                </td>
              </tr>
            ))}
          {!isLoading && rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-4 py-10 text-center text-muted-foreground">
                {labels.empty}
              </td>
            </tr>
          )}
          {!isLoading &&
            table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={cn(
                  "border-t border-rule first:border-0",
                  onRowClick && "cursor-pointer hover:bg-muted/60",
                )}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-4 py-2.5 align-middle">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
      {hasMore && (
        <div className="border-t border-rule p-2 text-center">
          <Button variant="ghost" size="sm" loading={isFetchingMore} onClick={onLoadMore}>
            {labels.loadMore}
          </Button>
        </div>
      )}
    </div>
  );
}
