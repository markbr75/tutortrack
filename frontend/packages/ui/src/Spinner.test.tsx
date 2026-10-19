import { render, screen } from "@testing-library/react";

import { Spinner } from "./Button";

describe("spinner", () => {
  it("as a page loader, says what it is doing and fades in late in faded ink", () => {
    render(<Spinner label="Loading…" />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Loading…");
    expect(status).toHaveClass("animate-appear", "text-muted-foreground");
  });

  it("inline, shows at once in the surrounding colour and still speaks", () => {
    render(<Spinner />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Loading");
    expect(status).not.toHaveClass("animate-appear");
  });

  it("keeps a fixed 16px ring whatever the caller passes", () => {
    const { container } = render(<Spinner className="size-6" label="Loading…" />);
    expect(container.querySelector("svg")).toHaveClass("size-4");
  });
});
