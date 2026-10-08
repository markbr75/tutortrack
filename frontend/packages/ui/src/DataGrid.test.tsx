import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ColumnDef } from "@tanstack/react-table";
import { DataGrid } from "./DataGrid";

interface Student {
  id: string;
  name: string;
}

const columns: ColumnDef<Student, unknown>[] = [{ header: "Name", accessorKey: "name" }];
const labels = { loading: "Loading…", empty: "Nothing here", loadMore: "Load more" };

describe("DataGrid", () => {
  it("renders rows", () => {
    render(
      <DataGrid
        rows={[{ id: "1", name: "Sam Patel" }]}
        columns={columns}
        getRowId={(r) => r.id}
        labels={labels}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Sam Patel" })).toBeInTheDocument();
  });

  it("shows the empty state", () => {
    render(<DataGrid rows={[]} columns={columns} getRowId={(r) => r.id} labels={labels} />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });

  it("loads more pages and handles row clicks", async () => {
    const onLoadMore = vi.fn();
    const onRowClick = vi.fn();
    render(
      <DataGrid
        rows={[{ id: "1", name: "Sam Patel" }]}
        columns={columns}
        getRowId={(r) => r.id}
        labels={labels}
        hasMore
        onLoadMore={onLoadMore}
        onRowClick={onRowClick}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    await userEvent.click(screen.getByRole("cell", { name: "Sam Patel" }));
    expect(onLoadMore).toHaveBeenCalledOnce();
    expect(onRowClick).toHaveBeenCalledWith({ id: "1", name: "Sam Patel" });
  });
});
