import { Navigate, useRoutes } from 'react-router-dom';
import AppLayout from '@/core/components/AppLayout';
import { WorkspacePage } from '@/features/workspace';
import { InventoryPage } from '@/features/workspace';
import { AddonStudioPage } from '@/features/addon-studio';
import { DeliveryPage } from '@/features/delivery';
import { PermissionsPage } from '@/features/permissions';
import { SettingsPage } from '@/features/settings';

export default function AppRoutes() {
  return useRoutes([
    {
      path: '/',
      element: <AppLayout />,
      children: [
        { index: true, element: <Navigate to="/studio" replace /> },
        { path: 'workspace', element: <WorkspacePage /> },
        { path: 'inventory', element: <InventoryPage /> },
        { path: 'studio', element: <AddonStudioPage /> },
        { path: 'delivery', element: <DeliveryPage /> },
        { path: 'permissions', element: <PermissionsPage /> },
        { path: 'settings', element: <SettingsPage /> },
        { path: '*', element: <Navigate to="/studio" replace /> },
      ],
    },
  ]);
}
