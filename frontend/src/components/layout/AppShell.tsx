'use client';

import { usePathname } from 'next/navigation';
import { Header } from './Header';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';

// Routes that don't require authentication
const PUBLIC_ROUTES = ['/login'];

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const isPublicRoute = PUBLIC_ROUTES.some(route => pathname.startsWith(route));

  // Login page has its own layout without header
  if (pathname === '/login') {
    return <>{children}</>;
  }

  return (
    <>
      <Header />
      <main>
        {isPublicRoute ? (
          children
        ) : (
          <ProtectedRoute>{children}</ProtectedRoute>
        )}
      </main>
    </>
  );
}
