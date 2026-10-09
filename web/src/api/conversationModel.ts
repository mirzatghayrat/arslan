import { request } from "./client";

/** 0.1.58 §6: the model this conversation runs on (null = the default). */
export const conversationModelApi = {
  get: (conversationId: string) =>
    request<{ choice: { config_id: number; model: string } | null }>(`/conversations/${encodeURIComponent(conversationId)}/model`),
  set: (conversationId: string, configId: number, model: string) =>
    request<{ choice: { config_id: number; model: string } }>(`/conversations/${encodeURIComponent(conversationId)}/model`,
      { method: "PUT", body: JSON.stringify({ config_id: configId, model }) }),
  clear: (conversationId: string) =>
    request<{ choice: null }>(`/conversations/${encodeURIComponent(conversationId)}/model`, { method: "DELETE" }),
};
