import { useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  text: string;
  options: string[] | null;
  multiSelect: boolean;
  hint: string;
  onSubmit: (answer: string) => void;
}

export default function QuestionView({ text, options, multiSelect, hint, onSubmit }: Props) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string[]>([]);
  const [textValue, setTextValue] = useState("");

  const toggle = (opt: string) => {
    if (multiSelect) {
      setSelected((prev) =>
        prev.includes(opt) ? prev.filter((o) => o !== opt) : [...prev, opt],
      );
    } else {
      setSelected([opt]);
    }
  };

  const submit = () => {
    const answer = options ? selected.join(", ") : textValue.trim();
    if (!answer) return;
    onSubmit(answer);
    setSelected([]);
    setTextValue("");
  };

  return (
    <div>
      <h2 className="mb-4 text-xl font-medium">{text}</h2>
      {hint && <p className="mb-3 text-sm text-white/50">{hint}</p>}

      {options ? (
        <div className="flex flex-col gap-2">
          {options.map((opt) => (
            <button
              key={opt}
              onClick={() => toggle(opt)}
              className={`rounded-lg border px-4 py-3 text-left ${
                selected.includes(opt)
                  ? "border-amber bg-amber/10"
                  : "border-white/15 hover:bg-white/5"
              }`}
            >
              {opt}
            </button>
          ))}
          {multiSelect && <p className="mt-1 text-xs text-white/40">{t("build.multi_hint")}</p>}
        </div>
      ) : (
        <input
          value={textValue}
          onChange={(e) => setTextValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={t("build.placeholder")}
          className="w-full rounded-lg border border-white/15 bg-white/5 px-4 py-3"
        />
      )}

      <button
        onClick={submit}
        className="mt-6 rounded-lg bg-amber px-5 py-2.5 font-medium text-black"
      >
        {t("build.next")}
      </button>
    </div>
  );
}
