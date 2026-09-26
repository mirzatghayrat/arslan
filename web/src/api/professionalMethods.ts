import { request } from "./client";

export interface ProfessionalMethod { key: string; revision: number; name: string; instructions: string }
export const professionalMethodsApi = {
  list: () => request<ProfessionalMethod[]>("/professional-methods"),
  revise: (method: ProfessionalMethod, name: string, instructions: string) => request<ProfessionalMethod>(
    `/professional-methods/${encodeURIComponent(method.key)}`, {
      method: "PUT", body: JSON.stringify({ expected_revision: method.revision, name, instructions }),
    }),
};
