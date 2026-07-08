// 开发用 Mock 数据（当前阶段前端不接后端，界面用这些数据渲染）

import type {
  Company,
  Site,
  InventorySnapshot,
  ChangeSpec,
  ConflictCheckItem,
  DeliveryRecord,
} from '@/core/types/domain';

export const mockCompanies: Company[] = [
  {
    code: 'shyjs',
    name: '上海医检所',
    shortName: 'shyjs',
    notes: '华东区重点客户',
    siteCount: 2,
    createdAt: '2026-06-20 09:12',
  },
  {
    code: 'bjsw',
    name: '北京生物医学',
    shortName: 'bjsw',
    notes: '',
    siteCount: 2,
    createdAt: '2026-06-25 14:30',
  },
  {
    code: 'hzlab',
    name: '杭州第三方检验',
    shortName: 'hzlab',
    notes: '试点阶段',
    siteCount: 1,
    createdAt: '2026-07-01 10:05',
  },
];

export const mockSites: Site[] = [
  {
    code: 'shyjs-maitux',
    name: '生产站点',
    companyCode: 'shyjs',
    url: 'http://121.40.188.203/Maitux',
    usage: 'inventory',
    senaiteVersion: '2.5.0',
    notes: '现网，摸底用',
    lastInventoryAt: '2026-07-08 10:30',
    status: 'online',
  },
  {
    code: 'shyjs-test',
    name: '测试站点',
    companyCode: 'shyjs',
    url: 'http://121.40.188.203/lims3',
    usage: 'test',
    senaiteVersion: '2.5.0',
    notes: '测试机，装 Addon 验证，可反复重置',
    lastInventoryAt: '2026-07-07 16:20',
    status: 'online',
  },
  {
    code: 'bjsw-prod',
    name: '生产站点',
    companyCode: 'bjsw',
    url: 'http://10.0.2.50:8080/bjsw',
    usage: 'inventory',
    senaiteVersion: '2.4.0',
    status: 'offline',
  },
  {
    code: 'bjsw-test',
    name: '测试站点',
    companyCode: 'bjsw',
    url: 'http://10.0.2.50:8080/bjsw-test',
    usage: 'test',
    senaiteVersion: '2.4.0',
    status: 'unknown',
  },
  {
    code: 'hzlab-prod',
    name: '生产站点',
    companyCode: 'hzlab',
    url: 'http://172.16.0.9/hzlab',
    usage: 'both',
    senaiteVersion: '2.5.0',
    status: 'unknown',
  },
];

export const mockInventories: InventorySnapshot[] = [
  {
    id: 'inv_20260708_103000',
    companyCode: 'shyjs',
    companyName: '上海医检所',
    siteCode: 'shyjs-maitux',
    siteName: '生产站点',
    siteUrl: 'http://121.40.188.203/Maitux',
    createdAt: '2026-07-08 10:30',
    senaiteVersion: '2.5.0',
    entityCount: 48,
    addonCount: 12,
    staleness: 'fresh',
  },
  {
    id: 'inv_20260705_090000',
    companyCode: 'shyjs',
    companyName: '上海医检所',
    siteCode: 'shyjs-maitux',
    siteName: '生产站点',
    siteUrl: 'http://121.40.188.203/Maitux',
    createdAt: '2026-07-05 09:00',
    senaiteVersion: '2.5.0',
    entityCount: 47,
    addonCount: 12,
    staleness: 'stale',
  },
  {
    id: 'inv_20260707_162000',
    companyCode: 'shyjs',
    companyName: '上海医检所',
    siteCode: 'shyjs-test',
    siteName: '测试站点',
    siteUrl: 'http://121.40.188.203/lims3',
    createdAt: '2026-07-07 16:20',
    senaiteVersion: '2.5.0',
    entityCount: 48,
    addonCount: 12,
    staleness: 'stale',
  },
];

export const mockChangeSpec: ChangeSpec = {
  version: '1.0',
  siteCode: 'shyjs-maitux',
  inventoryRef: 'inv_20260708_103000',
  changes: [
    {
      changeType: 'AddField',
      description: '为 AnalysisRequest 添加字符串字段 maitux_sample_code',
      typeId: 'AnalysisRequest',
      fieldName: 'maitux_sample_code',
      fieldType: 'StringField',
      required: false,
      framework: 'dexterity',
    },
    {
      changeType: 'UpdateListing',
      description: '在 Sample 列表视图显示 maitux_sample_code 列',
      typeId: 'Sample',
      addColumns: ['maitux_sample_code'],
      removeColumns: [],
    },
  ],
  risks: [{ level: 'low', message: '仅新增字段和列表列，不影响现有数据' }],
};

/** 冲突校验结果：需求 vs 摸底能力逐项比对 */
export const mockConflictChecks: ConflictCheckItem[] = [
  {
    changeType: 'AddField',
    target: 'AnalysisRequest.maitux_sample_code',
    status: 'ok',
    message: '目标类型 AnalysisRequest 存在，且无同名字段，可安全新增',
  },
  {
    changeType: 'UpdateListing',
    target: 'Sample 列表视图',
    status: 'ok',
    message: '目标类型 Sample 存在，列 maitux_sample_code 尚未展示',
  },
];

export const mockDeliveries: DeliveryRecord[] = [
  {
    id: 'apply_web_20260708_103000',
    addonName: 'shyjs.samplefield',
    version: '1.0.0',
    companyCode: 'shyjs',
    siteCode: 'shyjs-maitux',
    status: 'packaged',
    changeTypes: ['AddField', 'UpdateListing'],
    packageSizeKb: 34,
    createdAt: '2026-07-08 10:30',
  },
  {
    id: 'apply_web_20260707_161500',
    addonName: 'maitux.reporttemplate',
    version: '1.2.0',
    companyCode: 'shyjs',
    siteCode: 'shyjs-test',
    status: 'validated',
    changeTypes: ['CreateReportTemplateFromDocx'],
    packageSizeKb: 58,
    createdAt: '2026-07-07 16:15',
  },
  {
    id: 'apply_web_20260706_090000',
    addonName: 'bjsw.customfield',
    version: '1.0.0',
    companyCode: 'bjsw',
    siteCode: 'bjsw-test',
    status: 'failed',
    changeTypes: ['AddField'],
    packageSizeKb: 0,
    createdAt: '2026-07-06 09:00',
  },
];
