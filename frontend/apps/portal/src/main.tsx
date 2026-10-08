import "@tutortrack/ui/styles.css";

import { createI18n, I18nextProvider } from "@tutortrack/i18n";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { PortalHome } from "./PortalHome";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing");

createRoot(root).render(
  <StrictMode>
    <I18nextProvider i18n={createI18n("en-GB")}>
      <PortalHome />
    </I18nextProvider>
  </StrictMode>,
);
