import { WorkspaceProvider } from '@/core/context/WorkspaceContext';
import AppRoutes from '@/routes';

export default function App() {
  return (
    <WorkspaceProvider>
      <AppRoutes />
    </WorkspaceProvider>
  );
}
