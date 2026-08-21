/**
 * SshIdentityPanel — Arslan's own SSH public key, and how to put it on a machine.
 *
 * Deliberately not show-once (unlike McpTokenControl): a public key is meant to
 * be read again every time the user sets up another machine, and hiding it would
 * only push people toward passwords, which this product does not implement.
 *
 * The copy says what removal does and does not do. Forgetting the identity here
 * cannot reach into the other machine and delete the authorized_keys line — a
 * dialog that implied otherwise would leave a live key the user believes is gone.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Check, KeyRound, Trash2 } from "lucide-react";
import { api } from "../../api/client";

export default function SshIdentityPanel() {
  const { t } = useTranslation();
  const [publicKey, setPublicKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    api.getSshIdentity()
      .then((r) => { if (alive) setPublicKey(r.public_key); })
      .catch(() => { /* absent identity is a normal state, not an error to shout about */ });
    return () => { alive = false; };
  }, []);

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      setPublicKey((await api.createSshIdentity()).public_key);
    } catch {
      setError(t("settings.sshKeyError"));
    } finally {
      setBusy(false);
    }
  };

  const forget = async () => {
    setBusy(true);
    try {
      setPublicKey((await api.deleteSshIdentity()).public_key);
    } catch {
      setError(t("settings.sshKeyError"));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    await navigator.clipboard.writeText(publicKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="rounded-xl border border-border/60 bg-background/40 p-4 space-y-3"
         data-testid="ssh-identity-panel">
      <div className="flex items-center gap-2">
        <KeyRound className="w-3.5 h-3.5 text-primary" />
        <h5 className="text-[11px] font-bold text-foreground font-sans">
          {t("settings.sshKeyTitle")}
        </h5>
      </div>
      {publicKey ? (
        <>
          <p className="text-[10.5px] text-subtle-foreground font-sans">
            {t("settings.sshKeyHowto")}
          </p>
          <code data-testid="ssh-public-key"
                className="block break-all bg-surface border border-border rounded-lg px-3 py-2 text-[10.5px] text-foreground font-mono">
            {publicKey}
          </code>
          <div className="flex items-center gap-2">
            <button type="button" onClick={copy} disabled={busy}
                    data-testid="ssh-copy"
                    className="inline-flex items-center gap-1.5 text-[11px] text-foreground border border-border rounded-lg px-2.5 py-1.5 hover:border-primary">
              {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copied ? t("settings.sshKeyCopied") : t("settings.sshKeyCopy")}
            </button>
            <button type="button" onClick={forget} disabled={busy}
                    data-testid="ssh-forget"
                    className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground border border-border rounded-lg px-2.5 py-1.5 hover:border-danger hover:text-danger">
              <Trash2 className="w-3 h-3" />
              {t("settings.sshKeyForget")}
            </button>
          </div>
          <p className="text-[10.5px] text-muted-foreground font-sans">
            {t("settings.sshKeyForgetHint")}
          </p>
        </>
      ) : (
        <>
          <p className="text-[10.5px] text-subtle-foreground font-sans">
            {t("settings.sshKeyNone")}
          </p>
          <button type="button" onClick={create} disabled={busy}
                  data-testid="ssh-create"
                  className="text-[11px] text-foreground border border-border rounded-lg px-2.5 py-1.5 hover:border-primary">
            {t("settings.sshKeyCreate")}
          </button>
        </>
      )}
      {error ? <p className="text-[10.5px] text-danger font-sans">{error}</p> : null}
    </div>
  );
}
