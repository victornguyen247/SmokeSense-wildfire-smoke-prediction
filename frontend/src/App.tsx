import { AlertTokenPage } from "./pages/AlertTokenPage";
import { DashboardPage } from "./pages/DashboardPage";

// The email links (docs/alerts.md, section 2) open these paths; everything else is the map.
// Hosting serves index.html for any path (try_files in the production nginx config).
export default function App() {
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/alerts/confirm") return <AlertTokenPage kind="confirm" />;
  if (path === "/alerts/unsubscribe") return <AlertTokenPage kind="unsubscribe" />;
  return <DashboardPage />;
}
