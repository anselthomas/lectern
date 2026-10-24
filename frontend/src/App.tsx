import { ReactNode, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, ApiError, onLimit } from "./api";
import { hasSession } from "./auth";
import { Loading, TopNav, UpgradeModal } from "./components";
import { useMe } from "./state";
import Landing from "./pages/Landing";
import { Forgot, SignIn, SignUp, Verify } from "./pages/Auth";
import Onboarding from "./pages/Onboarding";
import Library from "./pages/Library";
import Structure from "./pages/Structure";
import BookMap from "./pages/BookMap";
import PreQuestion from "./pages/PreQuestion";
import Lesson from "./pages/Lesson";
import Explain from "./pages/Explain";
import Quiz from "./pages/Quiz";
import Review from "./pages/Review";
import Progress from "./pages/Progress";
import Notes from "./pages/Notes";
import Search from "./pages/Search";
import Notifications from "./pages/Notifications";
import Settings from "./pages/Settings";
import FinalTest from "./pages/FinalTest";
import { Help, Legal, NotFound } from "./pages/Static";
import Admin, { AdminUser } from "./pages/Admin";

function Private({ children, bare, admin }: { children: ReactNode; bare?: boolean; admin?: boolean }) {
  const { me, loading } = useMe();
  const loc = useLocation();
  if (loading) return <Loading />;
  if (!me) return <Navigate to={`/signin?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (!me.onboarded && loc.pathname !== "/onboarding" && !admin) return <Navigate to="/onboarding" replace />;
  if (admin && !me.is_admin) return <Navigate to="/library" replace />;
  return bare ? <>{children}</> : <><TopNav /><main>{children}</main></>;
}

export default function App() {
  const [limit, setLimit] = useState<ApiError | null>(null);
  const loc = useLocation();
  useEffect(() => { const off = onLimit(setLimit); return () => { off(); }; }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [loc.pathname]);
  // Screen-level usage for the admin view: the route shape only, ids replaced, nothing from the page itself.
  useEffect(() => {
    if (!hasSession()) return;
    const path = loc.pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, ":id").slice(0, 80);
    api("/track", { body: { path } }).catch(() => undefined);
  }, [loc.pathname]);
  return (
    <>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/signin" element={<SignIn />} />
        <Route path="/signup" element={<SignUp />} />
        <Route path="/verify" element={<Verify />} />
        <Route path="/forgot" element={<Forgot />} />
        <Route path="/privacy" element={<Legal kind="privacy" />} />
        <Route path="/terms" element={<Legal kind="terms" />} />
        <Route path="/refunds" element={<Legal kind="refunds" />} />
        <Route path="/onboarding" element={<Private bare><Onboarding /></Private>} />
        <Route path="/library" element={<Private><Library /></Private>} />
        <Route path="/books/:bookId/structure" element={<Private><Structure /></Private>} />
        <Route path="/books/:bookId" element={<Private><BookMap /></Private>} />
        <Route path="/books/:bookId/notes" element={<Private><Notes /></Private>} />
        <Route path="/books/:bookId/final" element={<Private><FinalTest /></Private>} />
        <Route path="/chapters/:chapterId/start" element={<Private><PreQuestion /></Private>} />
        <Route path="/chapters/:chapterId/explain" element={<Private><Explain /></Private>} />
        <Route path="/chapters/:chapterId/quiz" element={<Private><Quiz /></Private>} />
        <Route path="/sections/:sectionId" element={<Private bare><Lesson /></Private>} />
        <Route path="/review" element={<Private><Review /></Private>} />
        <Route path="/progress" element={<Private><Progress /></Private>} />
        <Route path="/search" element={<Private><Search /></Private>} />
        <Route path="/notifications" element={<Private><Notifications /></Private>} />
        <Route path="/settings" element={<Private><Settings /></Private>} />
        <Route path="/admin" element={<Private admin><Admin /></Private>} />
        <Route path="/admin/users/:userId" element={<Private admin><AdminUser /></Private>} />
        <Route path="/help" element={<Help />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      {limit && <UpgradeModal message={limit.message} onClose={() => setLimit(null)} />}
    </>
  );
}
