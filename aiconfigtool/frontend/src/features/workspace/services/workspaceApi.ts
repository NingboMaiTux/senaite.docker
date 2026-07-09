// workspace 数据访问：全部走真实后端。

import { apiClient } from '@/core/services/apiClient';
import type { Company, Site, InventorySnapshot } from '@/core/types/domain';

export const workspaceApi = {
  getCompanies: () =>
    apiClient.get<Company[]>('/companies'),

  createCompany: (company: Company) =>
    apiClient.post<Company>('/companies', company),

  updateCompany: (code: string, company: Company) =>
    apiClient.put<Company>(`/companies/${code}`, company),

  deleteCompany: (code: string) =>
    apiClient.del<void>(`/companies/${code}`),

  getSites: (companyCode: string) =>
    apiClient.get<Site[]>(`/companies/${companyCode}/sites`),

  createSite: (site: Site) =>
    apiClient.post<Site>(`/companies/${site.companyCode}/sites`, site),

  updateSite: (code: string, site: Site) =>
    apiClient.put<Site>(`/sites/${code}`, site),

  deleteSite: (code: string) =>
    apiClient.del<void>(`/sites/${code}`),

  testConnection: (siteCode: string) =>
    apiClient.post<{ reachable: boolean; url: string; reason?: string }>(
      `/sites/${siteCode}/test-connection`),

  getInventories: (siteCode?: string) => {
    const path = siteCode ? `/inventories?siteCode=${siteCode}` : '/inventories';
    return apiClient.get<InventorySnapshot[]>(path);
  },

  runInventory: (siteCode: string) =>
    apiClient.post<InventorySnapshot>('/inventory/run', { siteCode }),

  deleteInventory: (siteCode: string, inventoryId: string) =>
    apiClient.del<void>(`/sites/${siteCode}/inventories/${inventoryId}`),

  diffInventories: (siteA: string, invA: string, siteB: string, invB: string) =>
    apiClient.post<DiffResult>('/inventory/diff', { siteA: siteA, invA: invA, siteB: siteB, invB: invB }),
};

export interface TypeDiffItem {
  typeId: string;
  change: 'added' | 'removed' | 'modified';
  title: string;
  addedFields?: string[];
  removedFields?: string[];
  frameworkA?: string;
  frameworkB?: string;
}

export interface DiffResult {
  base: { site: string; inventory: string; createdAt: string };
  target: { site: string; inventory: string; createdAt: string };
  typeCountA: number;
  typeCountB: number;
  typeDiffs: TypeDiffItem[];
}
