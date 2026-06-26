import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./store/auth";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import SearchPage from "./pages/SearchPage";
import UploadPage from "./pages/UploadPage";
import JobsPage from "./pages/JobsPage";
import { Spinner } from "./components/ui";

export default function App() {
  const { principal, loading } = useAuth();

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center text-slate-400">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (!principal) return <LoginPage />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/search" element={<SearchPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="*" element={<Navigate to="/search" replace />} />
      </Route>
    </Routes>
  );
}
