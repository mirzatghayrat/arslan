import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function ChatInput({ onSend }: { onSend: (text: string) => void }) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const submit = () => {
    const text = value.trim();
    if (!text) return;
    onSend(text);
    setValue("");
  };
  return (
    <div className="flex gap-2 border-t border-white/10 pt-3">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder={t("chat.placeholder")}
        className="flex-1 rounded-lg border border-white/15 bg-white/5 px-4 py-2.5"
      />
      <button onClick={submit} className="rounded-lg bg-amber px-5 font-medium text-black">
        {t("chat.send")}
      </button>
    </div>
  );
}
