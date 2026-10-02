import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "@fontsource-variable/inter";
import "@fontsource/source-serif-4/500.css";
import "@fontsource/source-serif-4/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./index.css";
import { AuthProvider, useAuth } from "./lib/auth";
import { Spinner, ToastProvider } from "./components/ui";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Campaigns from "./pages/Campaigns";
import CampaignDetail from "./pages/CampaignDetail";
import Partners from "./pages/Partners";
import PartnerDetail from "./pages/PartnerDetail";
import Tasks from "./pages/Tasks";
import Outreach from "./pages/Outreach";
import Tripwires from "./pages/Tripwires";
import Intros from "./pages/Intros";
import Admin from "./pages/Admin";

try { document.documentElement.dataset.theme = localStorage.getItem("vanguard.theme") ?? "dark"; } catch { /* ignore */ }

function Guard({ admin, children }: { admin?: boolean; children: React.ReactNode }) {
  const { user, loading, isAdmin } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to="/login" replace />;
  if (admin && !isAdmin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<Guard><Layout /></Guard>}>
              <Route index element={<Dashboard />} />
              <Route path="campaigns" element={<Campaigns />} />
              <Route path="campaigns/:id" element={<CampaignDetail />} />
              <Route path="partners" element={<Partners />} />
              <Route path="partners/:id" element={<PartnerDetail />} />
              <Route path="tasks" element={<Tasks />} />
              <Route path="outreach" element={<Outreach />} />
              <Route path="tripwires" element={<Tripwires />} />
              <Route path="intros" element={<Intros />} />
              <Route path="admin" element={<Guard admin><Admin /></Guard>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  </StrictMode>,
);
