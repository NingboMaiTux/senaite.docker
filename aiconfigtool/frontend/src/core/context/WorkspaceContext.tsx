import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { workspaceApi } from '@/features/workspace/services/workspaceApi';
import type { Company } from '@/core/types/domain';

interface WorkspaceContextValue {
  companies: Company[];
  loading: boolean;
  currentCompanyCode: string | null;
  setCurrentCompanyCode: (code: string) => void;
  currentCompany: Company | null;
  addCompany: (c: Company) => void;
  updateCompany: (code: string, c: Company) => void;
  deleteCompany: (code: string) => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

const STORAGE_KEY = 'aiconfigtool.currentCompany';

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentCompanyCode, setCode] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY),
  );

  // 挂载时从后端加载公司
  useEffect(() => {
    let alive = true;
    workspaceApi.getCompanies().then((list) => {
      if (!alive) return;
      setCompanies(list);
      setCode((prev) => {
        if (prev && list.some((c) => c.code === prev)) return prev;
        return list[0]?.code ?? null;
      });
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const value = useMemo<WorkspaceContextValue>(() => {
    const setCurrentCompanyCode = (code: string) => {
      localStorage.setItem(STORAGE_KEY, code);
      setCode(code);
    };
    const addCompany = async (c: Company) => {
      setCompanies((prev) => [...prev, c]);
      setCurrentCompanyCode(c.code);
      try { await workspaceApi.createCompany(c); } catch { /* already in state */ }
    };
    const updateCompany = async (code: string, c: Company) => {
      setCompanies((prev) => prev.map((x) => (x.code === code ? c : x)));
      try { await workspaceApi.updateCompany(code, c); } catch { /* keep state */ }
    };
    const deleteCompany = async (code: string) => {
      setCompanies((prev) => {
        const next = prev.filter((x) => x.code !== code);
        if (code === currentCompanyCode && next[0]) setCurrentCompanyCode(next[0].code);
        return next;
      });
      try { await workspaceApi.deleteCompany(code); } catch { /* keep state */ }
    };
    return {
      companies, loading, currentCompanyCode, setCurrentCompanyCode,
      currentCompany: companies.find((c) => c.code === currentCompanyCode) ?? null,
      addCompany, updateCompany, deleteCompany,
    };
  }, [companies, loading, currentCompanyCode]);

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be used within WorkspaceProvider');
  return ctx;
}
