import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.tsx";
import "./index.css";

/** In mock mode, start MSW before the first request so every API call is answered by a fixture. */
async function enableMocking() {
  // Checked inline (not via constants/env) so the bundler can drop MSW and the fixtures
  // from builds where mock mode is off.
  if (import.meta.env.VITE_USE_MOCKS !== "true") return;
  const { worker } = await import("./mocks/browser");
  await worker.start({ onUnhandledRequest: "bypass", quiet: true });
}

function render() {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

// Render even if MSW fails to start (e.g. service worker blocked): the app then calls
// the API directly and shows its normal error states instead of a blank page.
enableMocking()
  .catch((err: unknown) => {
    console.error("Mock mode failed to start; API calls will go to VITE_API_BASE_URL.", err);
  })
  .finally(render);
