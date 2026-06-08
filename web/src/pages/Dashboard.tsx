import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import SpawnCard from "../components/spawn/SpawnCard";
import { useSpawnStore } from "../stores/spawnStore";

export default function Dashboard() {
  const { t } = useTranslation();
  const { spawns, loading, error, load, remove } = useSpawnStore();

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t("dashboard.title")}</h1>
        <Link
          to="/build"
          className="rounded-lg bg-amber px-4 py-2 font-medium text-black"
        >
          {t("dashboard.create")}
        </Link>
      </div>

      {error && <p className="text-red-400">{error}</p>}
      {loading && <p className="text-white/50">…</p>}

      {!loading && spawns.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/15 p-10 text-center">
          <p className="text-lg font-medium">{t("dashboard.empty_title")}</p>
          <p className="mt-1 text-white/50">{t("dashboard.empty_body")}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {spawns.map((s) => (
            <SpawnCard key={s.id} spawn={s} onDelete={(id) => void remove(id)} />
          ))}
        </div>
      )}
    </div>
  );
}
