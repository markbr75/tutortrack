import "@tutortrack/ui/styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { registerServiceWorker } from "./offline/client";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing");

registerServiceWorker();

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
