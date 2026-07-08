import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { mockCompanies } from '@/mocks/data';
import type { Company } from '@/core/types/domain';

interface WorkspaceContextValue {
  companies: Company[];
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
  const [companies, setCompanies] = useState<Company[]>(mockCompanies);
  const [currentCompanyCode, setCode] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY) ?? mockCompanies[0]?.code ?? null,
  );

  const value = useMemo<WorkspaceContextValue>(() => {
    const setCurrentCompanyCode = (code: string) => {
      localStorage.setItem(STORAGE_KEY, code);
      setCode(code);
    };
    const addCompany = (c: Company) => {
      setCompanies((prev) => [...prev, c]);
      setCurrentCompanyCode(c.code);
    };
    const updateCompany = (code: string, c: Company) => {
      setCompanies((prev) => prev.map((x) => (x.code === code ? c : x)));
    };
    const deleteCompany = (code: string) => {
      setCompanies((prev) => {
        const next = prev.filter((x) => x.code !== code);
        if (code === currentCompanyCode && next[0]) {
          setCurrentCompanyCode(next[0].code);
        }
        return next;
      });
    };
    return {
      companies,
      currentCompanyCode,
      setCurrentCompanyCode,
      currentCompany:
        companies.find((c) => c.code === currentCompanyCode) ?? null,
      addCompany,
      updateCompany,
      deleteCompany,
    };
  }, [companies, currentCompanyCode]);

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
