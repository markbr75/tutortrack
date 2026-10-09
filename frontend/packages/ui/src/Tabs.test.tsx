import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import { Tabs } from "./Tabs";

function Example() {
  const [tab, setTab] = useState<"a" | "b" | "c">("a");
  return (
    <Tabs
      label="Sections"
      tabs={[
        { key: "a", label: "Alpha" },
        { key: "b", label: "Beta" },
        { key: "c", label: "Gamma" },
      ]}
      value={tab}
      onChange={setTab}
    >
      <p>Panel {tab}</p>
    </Tabs>
  );
}

describe("Tabs", () => {
  it("supports arrow, Home and End keys with roving focus", () => {
    render(<Example />);
    const alpha = screen.getByRole("tab", { name: "Alpha" });
    expect(alpha).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(alpha, { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Gamma" })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel c");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Gamma" }), { key: "Home" });
    expect(alpha).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(alpha, { key: "End" });
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Gamma");
  });
});
