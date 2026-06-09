import { Route, Routes } from "react-router-dom";
import ErrorBoundary from "./components/layout/ErrorBoundary";
import Header from "./components/layout/Header";
import Build from "./pages/Build";
import Chat from "./pages/Chat";
import Conversation from "./pages/Conversation";
import Dashboard from "./pages/Dashboard";
import NotFound from "./pages/NotFound";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <div className="app-bg text-white">
      <Header />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Conversation />} />
            <Route path="/spawns" element={<Dashboard />} />
            <Route path="/build" element={<Build />} />
            <Route path="/chat/:spawnId" element={<Chat />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
