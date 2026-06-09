import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import type { UserFact } from "../../types";

export default function FactsPanel() {
  const { t } = useTranslation();
  const [facts, setFacts] = useState<UserFact[]>([]);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    void api.listFacts().then(setFacts);
  }, []);

  const add = async () => {
    const content = draft.trim();
    if (!content) return;
    const created = await api.addFact({ content, sensitive: false });
    setFacts((f) => [...f, created]);
    setDraft("");
  };

  const saveEdit = async (id: number, content: string) => {
    const updated = await api.updateFact(id, { content });
    setFacts((f) => f.map((x) => (x.id === id ? updated : x)));
  };

  const remove = async (id: number) => {
    await api.deleteFact(id);
    setFacts((f) => f.filter((x) => x.id !== id));
  };

  return (
    <section className="mt-4 space-y-3 rounded-xl border border-white/10 bg-white/5 p-5">
      <h2 className="font-medium text-amber">{t("facts.section")}</h2>
      <p className="text-xs text-white/40">{t("facts.subtitle")}</p>

      {facts.length === 0 && <p className="text-sm text-white/50">{t("facts.empty")}</p>}

      <ul className="space-y-2">
        {facts.map((f) => (
          <li key={f.id} className="flex items-center gap-2">
            <input
              defaultValue={f.content}
              onBlur={(e) => {
                if (e.target.value.trim() && e.target.value !== f.content) {
                  void saveEdit(f.id, e.target.value.trim());
                }
              }}
              className="flex-1 rounded-lg bg-white/10 px-3 py-1.5 text-sm"
            />
            {f.sensitive && <span className="text-xs text-amber/70">{t("facts.sensitive")}</span>}
            <button
              onClick={() => void remove(f.id)}
              className="rounded-lg px-3 py-1.5 text-sm text-red-300 hover:bg-red-500/10"
            >
              {t("facts.delete")}
            </button>
          </li>
        ))}
      </ul>

      <div className="flex gap-2 pt-1">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void add()}
          placeholder={t("facts.add_placeholder")}
          className="flex-1 rounded-lg bg-white/10 px-3 py-2 text-sm"
        />
        <button onClick={() => void add()} className="rounded-lg bg-amber px-4 text-sm font-medium text-black">
          {t("facts.add")}
        </button>
      </div>
    </section>
  );
}
