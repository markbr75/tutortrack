import { fireEvent, render, screen } from "@testing-library/react";

import { CookieBanner, readCookieConsent } from "./CookieBanner";

const labels = {
  title: "Cookies",
  body: "We use cookies.",
  acceptAll: "Accept all",
  rejectAll: "Reject non-essential",
  customise: "Customise",
  save: "Save choices",
  analytics: "Analytics",
  marketing: "Marketing",
  necessary: "Necessary",
};

beforeEach(() => {
  document.cookie = "tt_consent=; Max-Age=0; Path=/";
});

describe("CookieBanner", () => {
  it("offers reject as prominently as accept and remembers the choice", () => {
    render(<CookieBanner labels={labels} />);
    const accept = screen.getByRole("button", { name: "Accept all" });
    const reject = screen.getByRole("button", { name: "Reject non-essential" });
    expect(reject.className).toBe(accept.className);
    fireEvent.click(reject);
    expect(readCookieConsent()).toMatchObject({ analytics: false, marketing: false });
    expect(screen.queryByRole("region", { name: "Cookies" })).not.toBeInTheDocument();
  });

  it("lets visitors choose categories", () => {
    render(<CookieBanner labels={labels} />);
    fireEvent.click(screen.getByRole("button", { name: "Customise" }));
    fireEvent.click(screen.getByLabelText("Analytics"));
    fireEvent.click(screen.getByRole("button", { name: "Save choices" }));
    expect(readCookieConsent()).toMatchObject({ analytics: true, marketing: false });
  });

  it("stays hidden once a choice exists", () => {
    document.cookie = `tt_consent=${encodeURIComponent(
      JSON.stringify({ necessary: true, analytics: true, marketing: true, version: 1 }),
    )}; Path=/`;
    render(<CookieBanner labels={labels} />);
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });
});
