import { Route, Routes } from "react-router-dom";
import Header from "./components/layout/Header";
import Build from "./pages/Build";
import Chat from "./pages/Chat";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <div className="app-bg text-white">
      <Header />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/build" element={<Build />} />
          <Route path="/chat/:spawnId" element={<Chat />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
