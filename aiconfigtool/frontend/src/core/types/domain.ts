// 领域类型定义（与后端 domain/ 对应）

// ── 公司 / 站点 ──

/** 站点用途：摸底站（扫能力）/ 测试站（装 Addon 验证）。一个站点可兼任 */
export type SiteUsage = 'inventory' | 'test' | 'both';

export interface Company {
  code: string;
  name: string;
  shortName: string; // 简称，用于 Addon 命名空间
  notes?: string;
  siteCount: number;
  createdAt: string;
}

export interface Site {
  code: string; // 工具内唯一标识
  name: string; // 显示名，如 "生产站点"
  companyCode: string;
  url: string; // 一个 URL 就是一个站点，如 http://121.40.188.203/Maitux
  usage: SiteUsage;
  senaiteVersion: string;
  notes?: string;
  lastInventoryAt?: string;
  status: 'online' | 'offline' | 'unknown';
}

// ── Inventory 摸底文件 ──

/** 摸底文件：生成时打上公司+站点+时间标签，随身携带 */
export interface InventorySnapshot {
  id: string;
  companyCode: string;
  companyName: string; // 冗余存显示名，列表直接可读
  siteCode: string;
  siteName: string;
  siteUrl: string;
  createdAt: string;
  senaiteVersion: string;
  entityCount: number;
  addonCount: number;
  staleness: 'fresh' | 'stale';
}

export interface InventoryFieldSummary {
  name: string;
  type: string;
  required: boolean;
}

export interface InventoryTypeSummary {
  title: string;
  framework: string;
  addPermission: string;
  fields: InventoryFieldSummary[];
  behaviors: string[];
}

export interface InventorySummary {
  types: Record<string, InventoryTypeSummary>;
  typeCount: number;
}

export interface InventoryDetail extends InventorySnapshot {
  summary: InventorySummary;
}

// ── Change Spec ──

export type ChangeType =
  | 'AddField'
  | 'UpdateField'
  | 'RemoveField'
  | 'UpdateListing'
  | 'UpdateWorkflow'
  | 'UpdatePermission'
  | 'CreateReportTemplateFromDocx';

export type Framework = 'dexterity' | 'archetypes';

export interface ChangeItem {
  changeType: ChangeType;
  description: string;
  typeId?: string;
  typeTitle?: string;
  fieldName?: string;
  fieldTitle?: string;
  fieldDescription?: string;
  fieldType?: string;
  required?: boolean;
  framework?: Framework;
  addColumns?: string[];
  removeColumns?: string[];
  targetType?: string;
  targetTitle?: string;
  [key: string]: unknown;
}

export type RiskLevel = 'low' | 'medium' | 'high';

export interface RiskItem {
  level: RiskLevel;
  message: string;
}

export interface ChangeSpec {
  version: string;
  siteCode: string;
  inventoryRef: string; // 引用的摸底文件 ID
  changes: ChangeItem[];
  risks: RiskItem[];
}

// ── 冲突校验（需求 vs 能力）──

export type ConflictStatus = 'ok' | 'conflict';

/** 单条变更项与摸底能力的比对结果 */
export interface ConflictCheckItem {
  changeType: ChangeType;
  target: string; // 目标类型/字段的可读描述
  status: ConflictStatus;
  message: string; // ok 的理由 或 冲突原因
}

// ── Addon 项目 / 交付 ──

export type NamespaceMode = 'general' | 'custom';

export interface AddonMeta {
  namespaceMode: NamespaceMode;
  namespace: string;
  functionName: string;
  version: string;
  description: string;
  dependencies: string[];
}

export type GateStatus = 'pending' | 'running' | 'passed' | 'failed';

export interface GateResult {
  gate: 'Gate0' | 'Gate1' | 'Gate2';
  label: string;
  status: GateStatus;
  detail?: string;
}

export type DeliveryStatus = 'validated' | 'packaged' | 'failed';

export interface DeliveryRecord {
  id: string;
  addonName: string;
  version: string;
  companyCode: string;
  siteCode: string;
  status: DeliveryStatus;
  changeTypes: ChangeType[];
  packageSizeKb: number;
  createdAt: string;
}

// ── AI 提供商 ──

export type AIProvider = 'deterministic' | 'ollama' | 'cloud';
