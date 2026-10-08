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
    <div className={cn("overflow-x-auto rounded-md border border-border", className)}>
      <table className="w-full text-left text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="bg-muted text-muted-foreground">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id} scope="col" className="px-3 py-2 font-medium">
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {isLoading && (
            <tr>
              <td colSpan={columns.length} className="px-3 py-6 text-center">
                <Spinner className="size-5" label={labels.loading} />
              </td>
            </tr>
          )}
          {!isLoading && rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-3 py-6 text-center text-muted-foreground">
                {labels.empty}
              </td>
            </tr>
          )}
          {!isLoading &&
            table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={cn(
                  "border-t border-border",
                  onRowClick && "cursor-pointer hover:bg-muted",
                )}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2 align-top">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
      {hasMore && (
        <div className="border-t border-border p-2 text-center">
          <Button variant="ghost" size="sm" loading={isFetchingMore} onClick={onLoadMore}>
            {labels.loadMore}
          </Button>
        </div>
      )}
    </div>
  );
}
