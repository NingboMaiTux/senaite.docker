import { useEffect, useReducer } from 'react';
import type {
  AddonMeta,
  ChangeSpec,
  ConflictCheckItem,
  GateResult,
  AIProvider,
} from '@/core/types/domain';

// 6 步：选站点 → 描述需求 → 冲突校验 → 配置元信息 → 生成 → 测试验证/下载
export interface WorkflowState {
  currentStep: number; // 0..5
  // 步骤1：选摸底站点
  siteCode: string | null;
  autoInventory: boolean; // 自动摸底（默认勾选）
  inventoryRef: string | null; // 取消自动摸底时手动选的摸底文件
  // 步骤2：描述需求
  naturalLanguageInput: string;
  aiProvider: AIProvider;
  // 步骤2 产出
  changeSpec: ChangeSpec | null;
  // 步骤3：冲突校验
  conflictChecks: ConflictCheckItem[];
  conflictPassed: boolean;
  // 步骤4：配置元信息
  addonMeta: AddonMeta | null;
  // 步骤5：生成
  generationStatus: 'idle' | 'running' | 'success' | 'failed';
  gateResults: GateResult[];
  packageId: string | null;
  packageSizeKb: number;
  // 步骤6：测试验证
  testSiteCode: string | null;
  verifyStatus: 'idle' | 'running' | 'passed' | 'failed';
}

export const initialWorkflowState: WorkflowState = {
  currentStep: 0,
  siteCode: null,
  autoInventory: true,
  inventoryRef: null,
  naturalLanguageInput: '',
  aiProvider: 'ollama',
  changeSpec: null,
  conflictChecks: [],
  conflictPassed: false,
  addonMeta: null,
  generationStatus: 'idle',
  gateResults: [],
  packageId: null,
  packageSizeKb: 0,
  testSiteCode: null,
  verifyStatus: 'idle',
};

export type WorkflowAction =
  | { type: 'NEXT' }
  | { type: 'PREV' }
  | { type: 'GOTO'; step: number }
  | { type: 'SET_SITE'; siteCode: string }
  | { type: 'SET_AUTO_INVENTORY'; value: boolean }
  | { type: 'SET_INVENTORY_REF'; ref: string | null }
  | { type: 'SET_NL'; text: string }
  | { type: 'SET_PROVIDER'; provider: AIProvider }
  | { type: 'SET_CHANGE_SPEC'; spec: ChangeSpec }
  | { type: 'SET_CONFLICT'; checks: ConflictCheckItem[]; passed: boolean }
  | { type: 'SET_ADDON_META'; meta: AddonMeta }
  | { type: 'SET_GENERATION_STATUS'; status: WorkflowState['generationStatus'] }
  | { type: 'SET_GATE_RESULTS'; results: GateResult[] }
  | { type: 'SET_GENERATE_RESULT'; packageId: string; sizeKb: number }
  | { type: 'SET_TEST_SITE'; siteCode: string }
  | { type: 'SET_VERIFY_STATUS'; status: WorkflowState['verifyStatus'] }
  | { type: 'RESET' };

function reducer(state: WorkflowState, action: WorkflowAction): WorkflowState {
  switch (action.type) {
    case 'NEXT':
      return { ...state, currentStep: Math.min(state.currentStep + 1, 5) };
    case 'PREV':
      return { ...state, currentStep: Math.max(state.currentStep - 1, 0) };
    case 'GOTO':
      return { ...state, currentStep: action.step };
    case 'SET_SITE':
      return { ...state, siteCode: action.siteCode };
    case 'SET_AUTO_INVENTORY':
      return { ...state, autoInventory: action.value };
    case 'SET_INVENTORY_REF':
      return { ...state, inventoryRef: action.ref };
    case 'SET_NL':
      return { ...state, naturalLanguageInput: action.text };
    case 'SET_PROVIDER':
      return { ...state, aiProvider: action.provider };
    case 'SET_CHANGE_SPEC':
      return { ...state, changeSpec: action.spec };
    case 'SET_CONFLICT':
      return {
        ...state,
        conflictChecks: action.checks,
        conflictPassed: action.passed,
      };
    case 'SET_ADDON_META':
      return { ...state, addonMeta: action.meta };
    case 'SET_GENERATION_STATUS':
      return { ...state, generationStatus: action.status };
    case 'SET_GATE_RESULTS':
      return { ...state, gateResults: action.results };
    case 'SET_GENERATE_RESULT':
      return { ...state, packageId: action.packageId, packageSizeKb: action.sizeKb };
    case 'SET_TEST_SITE':
      return { ...state, testSiteCode: action.siteCode };
    case 'SET_VERIFY_STATUS':
      return { ...state, verifyStatus: action.status };
    case 'RESET':
      return initialWorkflowState;
    default:
      return state;
  }
}

const STORAGE_KEY = 'aiconfigtool.workflow';

function loadState(): WorkflowState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...initialWorkflowState, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return initialWorkflowState;
}

export function useAddonWorkflow() {
  const [state, dispatch] = useReducer(reducer, null, loadState);

  // 每次 state 变化自动缓存
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  return { state, dispatch };
}
