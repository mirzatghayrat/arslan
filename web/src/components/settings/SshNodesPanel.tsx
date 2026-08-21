/**
 * SshNodesPanel — the machines Arslan may reach, and how to stop it (P3c).
 *
 * Revocation copy is the careful part. Removing a machine here does two things
 * and pointedly not a third: Arslan forgets the machine and its pinned host key,
 * but the authorized_keys line on that machine is still there, and only somebody
 * with access to it can remove that. A user who believes a key is gone when it
 * is not is worse off than one who was told to go delete it.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Trash2, Server } from "lucide-react";
import { api } from "../../api/client";
import type { SshNode } from "../../api/client.types";

export default function SshNodesPanel() {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<SshNode[]>([]);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setNodes((await api.listSshNodes()).nodes);
    } catch {
      /* an empty list and a failed fetch look the same to the user here, and
         neither is worth an alarm on a settings pane */
    }
  };

  useEffect(() => { void load(); }, []);

  const revoke = async (id: number) => {
    setBusy(true);
    try {
      await api.revokeSshNode(id);
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-border/60 bg-background/40 p-4 space-y-3"
         data-testid="ssh-nodes-panel">
      <div className="flex items-center gap-2">
        <Server className="w-3.5 h-3.5 text-primary" />
        <h5 className="text-[11px] font-bold text-foreground font-sans">
          {t("settings.sshNodesTitle")}
        </h5>
      </div>
      {nodes.length === 0 ? (
        <p className="text-[10.5px] text-subtle-foreground font-sans" data-testid="ssh-nodes-empty">
          {t("settings.sshNodesEmpty")}
        </p>
      ) : (
        <ul className="space-y-2" data-testid="ssh-nodes-list">
          {nodes.map((n) => (
            <li key={n.id} className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[11px] text-foreground font-sans font-semibold">{n.name}</div>
                <div className="text-[10.5px] text-muted-foreground font-mono break-all">
                  {n.user}@{n.host}
                </div>
                {n.fingerprints.map((fp) => (
                  <div key={fp} className="text-[10px] text-subtle-foreground font-mono break-all">
                    {fp}
                  </div>
                ))}
              </div>
              <button type="button" disabled={busy} onClick={() => revoke(n.id)}
                      data-testid={`ssh-node-revoke-${n.id}`}
                      className="shrink-0 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground border border-border rounded-lg px-2.5 py-1.5 hover:border-danger hover:text-danger">
                <Trash2 className="w-3 h-3" />
                {t("settings.sshNodeRevoke")}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="text-[10.5px] text-muted-foreground font-sans">
        {t("settings.sshNodesGateNote")}
      </p>
      <p className="text-[10.5px] text-muted-foreground font-sans">
        {t("settings.sshNodeRevokeHint")}
      </p>
    </div>
  );
}
