import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { AppLayout } from "@/components/layout/AppLayout";
import { AuthProvider } from "@/context/auth";
import { useAuth } from "@/context/use-auth";
import { EnvsProvider } from "@/context/envs";
import { LanguageProvider } from "@/context/lang";
import { PrefsProvider } from "@/context/prefs";
import { ThemeProvider } from "@/context/theme";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { LoginPage } from "@/pages/LoginPage";
import { OAuthCallbackPage } from "@/pages/OAuthCallbackPage";
import { DevicesPage } from "@/pages/DevicesPage";
import { NodesPage } from "@/pages/NodesPage";
import { EventsPage } from "@/pages/EventsPage";
import { AlertsPage } from "@/pages/AlertsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { Loader2 } from "lucide-react";

const DeviceDetailPage = lazy(() => import("@/pages/DeviceDetailPage").then((m) => ({ default: m.DeviceDetailPage })));

function FullScreenSpinner() {
  return (
    <div className="flex h-dvh items-center justify-center">
      <Loader2 className="text-muted-foreground size-8 animate-spin" />
    </div>
  );
}

function RequireAuth() {
  const { token, ready } = useAuth();
  const location = useLocation();

  if (!ready) return <FullScreenSpinner />;
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

function GuestOnly({ children }: { children: React.ReactNode }) {
  const { token, ready } = useAuth();
  if (!ready) return <FullScreenSpinner />;
  if (token) return <Navigate to="/devices" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <ThemeProvider>
      <LanguageProvider>
      <EnvsProvider>
        <AuthProvider>
          <PrefsProvider>
            <TooltipProvider>
              <BrowserRouter>
                <Routes>
                  <Route
                    path="/login"
                    element={
                      <GuestOnly>
                        <LoginPage />
                      </GuestOnly>
                    }
                  />
                  <Route path="/oauth/callback/:provider" element={<OAuthCallbackPage />} />
                  <Route element={<RequireAuth />}>
                    <Route element={<AppLayout />}>
                      <Route index element={<Navigate to="/devices" replace />} />
                      <Route path="/devices" element={<ErrorBoundary><DevicesPage /></ErrorBoundary>}>
                        <Route
                          path=":deviceId"
                          element={
                            <ErrorBoundary>
                              <Suspense fallback={<FullScreenSpinner />}>
                                <DeviceDetailPage />
                              </Suspense>
                            </ErrorBoundary>
                          }
                        />
                      </Route>
                      <Route path="/nodes" element={<ErrorBoundary><NodesPage /></ErrorBoundary>} />
                      <Route path="/events" element={<ErrorBoundary><EventsPage /></ErrorBoundary>} />
                      <Route path="/alerts" element={<ErrorBoundary><AlertsPage /></ErrorBoundary>} />
                      <Route path="/settings" element={<ErrorBoundary><SettingsPage /></ErrorBoundary>} />
                    </Route>
                  </Route>
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </BrowserRouter>
              <Toaster />
            </TooltipProvider>
          </PrefsProvider>
        </AuthProvider>
      </EnvsProvider>
      </LanguageProvider>
    </ThemeProvider>
  );
}
