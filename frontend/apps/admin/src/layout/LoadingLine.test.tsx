import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";

import { LoadingLine } from "./AppShell";

function Page({ queryKey, fn }: { queryKey: string; fn: () => Promise<number> }) {
  useQuery({ queryKey: [queryKey], queryFn: fn });
  return null;
}

function setup(fn: () => Promise<number>, seed?: number) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (seed !== undefined) client.setQueryData(["page"], seed);
  render(
    <QueryClientProvider client={client}>
      <LoadingLine />
      <Page queryKey="page" fn={fn} />
    </QueryClientProvider>,
  );
}

describe("loading line", () => {
  it("runs while a screen's first data is on its way, then goes", async () => {
    let finish: (n: number) => void = () => {};
    setup(() => new Promise<number>((resolve) => (finish = resolve)));
    expect(await screen.findByTestId("loading-line")).toBeInTheDocument();
    await act(async () => finish(1));
    await waitFor(() => expect(screen.queryByTestId("loading-line")).not.toBeInTheDocument());
  });

  it("stays out of the way when data is only being refreshed", async () => {
    setup(() => new Promise<number>(() => {}), 1);
    await act(async () => {});
    expect(screen.queryByTestId("loading-line")).not.toBeInTheDocument();
  });
});
