// Addon 工坊 API：对接后端真实端点（parse/conflict-check/generate/download）

import { apiClient } from '@/core/services/apiClient';
import type {
  ChangeSpec,
  ConflictCheckItem,
} from '@/core/types/domain';

export interface ParseReq {
  siteCode: string;
  inventoryRef: string;
  text: string;
}

export interface ConflictCheckReq {
  siteCode: string;
  inventoryRef: string;
  changes: ChangeSpec['changes'];
}

export interface GenerateReq {
  siteCode: string;
  inventoryRef: string;
  changes: ChangeSpec['changes'];
  meta: {
    namespace: string;
    functionName: string;
    version: string;
    description: string;
    dependencies?: string[];
  };
}

export interface GenerateResult {
  packageId: string;
  fullName: string;
  version: string;
  zipName: string;
  packageSizeKb: number;
  fileCount: number;
  gate2: { passed: boolean; missing: string[] };
  deployDocName: string;
}

export interface ConflictCheckResult {
  checks: ConflictCheckItem[];
  passed: boolean;
  inventoryRef: string;
  siteCode: string;
}

export const addonStudioApi = {
  parseRequirement: (req: ParseReq) =>
    apiClient.post<ChangeSpec>('/addon-studio/parse-requirement', req),

  conflictCheck: (req: ConflictCheckReq) =>
    apiClient.post<ConflictCheckResult>('/addon-studio/conflict-check', req),

  generate: (req: GenerateReq) =>
    apiClient.post<GenerateResult>('/addon-studio/generate', req),

  downloadUrl: (packageId: string) =>
    `/api/addon-studio/download/${packageId}`,
};
