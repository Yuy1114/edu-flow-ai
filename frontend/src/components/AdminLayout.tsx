import { useState, type ReactNode } from "react";
import { useAdminLayout } from "../hooks/useAdminLayout";
import AdminSidebar from "../ui/AdminSidebar";
import AdminHeader from "../ui/AdminHeader";

interface AdminLayoutProps {
  children: ReactNode;
}

export default function AdminLayout({ children }: AdminLayoutProps) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { menus, activePath, displayName, role, handleLogout } =
    useAdminLayout();

  return (
    <div className="flex h-screen overflow-hidden">
      <div className="hidden lg:block"><AdminSidebar menus={menus} activePath={activePath} /></div>
      {mobileMenuOpen && <div className="fixed inset-0 z-50 flex lg:hidden"><button className="absolute inset-y-0 left-64 right-0 bg-black/60" aria-label="关闭导航" onClick={() => setMobileMenuOpen(false)} /><div className="relative"><AdminSidebar menus={menus} activePath={activePath} onNavigate={() => setMobileMenuOpen(false)} /></div></div>}
      <div className="flex flex-col flex-1 min-w-0">
        <AdminHeader
          displayName={displayName}
          role={role}
          onLogout={handleLogout}
          onMenuOpen={() => setMobileMenuOpen(true)}
        />
        <main className="flex-1 overflow-auto bg-gray-900 p-3 sm:p-5">
          {children}
        </main>
      </div>
    </div>
  );
}
