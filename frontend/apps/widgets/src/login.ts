import { html } from "lit";

import { TtWidget } from "./base";
import { t } from "./strings";

/** `<tt-login portal="client|tutor|staff">`: a button to the organisation's portal or app
 * (its custom domain when connected). */
export class TtLogin extends TtWidget {
  static properties = { ...TtWidget.properties, portal: { type: String } };

  declare portal: string;

  constructor() {
    super();
    this.portal = "";
  }

  static styles = [TtWidget.baseStyles];

  render() {
    if (!this.brand) return this.status();
    const portal = this.portal || String(this.options.portal ?? "client");
    const href =
      portal === "staff"
        ? this.brand.login_url
        : portal === "tutor"
          ? `${this.brand.portal_url}tutor`
          : this.brand.portal_url;
    const label =
      String(this.options.button_text ?? "") ||
      (portal === "staff"
        ? t("portalStaff")
        : portal === "tutor"
          ? t("portalTutor")
          : t("portalClient"));
    return html`<a class="button" href=${href}>${label}</a>`;
  }
}

if (!customElements.get("tt-login")) customElements.define("tt-login", TtLogin);

declare global {
  interface HTMLElementTagNameMap {
    "tt-login": TtLogin;
  }
}
