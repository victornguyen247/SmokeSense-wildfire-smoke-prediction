import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.tsx";
import { USE_MOCKS } from "./constants/env";
import "./index.css";

/** In mock mode, start MSW before the first request so every API call is answered by a fixture. */
async function enableMocking() {
  if (!USE_MOCKS) return;
  // Loaded only in mock mode, so production builds never download MSW or the fixtures.
  const { worker } = await import("./mocks/browser");
  await worker.start({ onUnhandledRequest: "bypass", quiet: true });
}

enableMocking().then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
