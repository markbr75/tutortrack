import type { Meta, StoryObj } from "@storybook/react";

import type { ColumnDef } from "@tanstack/react-table";
import { DataGrid } from "./DataGrid";

interface Lesson {
  id: string;
  student: string;
  subject: string;
  when: string;
}

const columns: ColumnDef<Lesson, unknown>[] = [
  { header: "Student", accessorKey: "student" },
  { header: "Subject", accessorKey: "subject" },
  { header: "When", accessorKey: "when" },
];

const rows: Lesson[] = [
  { id: "1", student: "Sam Patel", subject: "GCSE Maths", when: "Thu 16:00" },
  { id: "2", student: "Ava Jones", subject: "A-Level Chemistry", when: "Fri 17:30" },
];

const meta: Meta<typeof DataGrid<Lesson>> = {
  title: "Data/DataGrid",
  component: DataGrid,
  args: {
    rows,
    columns,
    getRowId: (row: Lesson) => row.id,
    labels: { loading: "Loading…", empty: "No lessons", loadMore: "Load more" },
  },
};
export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Loading: Story = { args: { isLoading: true } };
export const Empty: Story = { args: { rows: [] } };
export const WithMorePages: Story = { args: { hasMore: true } };
