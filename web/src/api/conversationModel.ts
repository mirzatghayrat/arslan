import { request } from "./client";

type Choice = { config_id: number; model: string };
/** v0.1.64: what the conversation's next text turn really runs on, as the server resolves it; null before any
 *  config exists. */
export type EffectiveModel = { config_id: number; model: string; provider: string } | null;

/** 0.1.58 §6: the model this conversation runs on (null = the default), and what that resolves to. */
export const conversationModelApi = {
  get: (conversationId: string) =>
    request<{ choice: Choice | null; effective?: EffectiveModel }>(`/conversations/${encodeURIComponent(conversationId)}/model`),
  set: (conversationId: string, configId: number, model: string) =>
    request<{ choice: Choice; effective?: EffectiveModel }>(`/conversations/${encodeURIComponent(conversationId)}/model`,
      { method: "PUT", body: JSON.stringify({ config_id: configId, model }) }),
  clear: (conversationId: string) =>
    request<{ choice: null; effective?: EffectiveModel }>(`/conversations/${encodeURIComponent(conversationId)}/model`, { method: "DELETE" }),
};
