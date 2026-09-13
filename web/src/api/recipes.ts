import { request } from "./client";

export interface RecipeStep {
  key: string; name: string; spawn_id: number; task: string;
  depends_on: string[]; requires_approval: boolean;
}
export interface RecipeSpec { name: string; max_parallel: number; steps: RecipeStep[] }
export interface RecipeVersion { id: number; key: string; version: number; name: string; spec: RecipeSpec }
export interface RecipeNode { status: string; output?: string; error?: string; run_id?: number }
export interface RecipeExecution {
  id: number; recipe_id: number; input: string; status: string; run_id?: number; error?: string;
  checkpoint: { steps?: Record<string, RecipeNode>; approved?: string[] };
}
export const recipeApi = {
  versions: () => request<RecipeVersion[]>("/recipes"),
  executions: () => request<RecipeExecution[]>("/recipe-executions"),
  save: (key: string, spec: RecipeSpec) => request<RecipeVersion>(`/recipes/${encodeURIComponent(key)}/versions`,
    { method: "POST", body: JSON.stringify(spec) }),
  start: (recipe_id: number, input: string, request_key: string) => request<RecipeExecution>("/recipe-executions",
    { method: "POST", body: JSON.stringify({ recipe_id, input, request_key }) }),
  resume: (id: number, approve_steps: string[], retry_unfinished: boolean) => request<RecipeExecution>(
    `/recipe-executions/${id}/resume`, { method: "POST", body: JSON.stringify({ approve_steps, retry_unfinished }) }),
  cancel: (id: number) => request(`/recipe-executions/${id}/cancel`, { method: "POST" }),
};
