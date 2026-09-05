import { Link } from "@tanstack/react-router";

interface MenuItem {
  path: string;
  label: string;
}

interface AdminSidebarProps {
  menus: MenuItem[];
  activePath: string;
  onNavigate?: () => void;
}

export default function AdminSidebar({ menus, activePath, onNavigate }: AdminSidebarProps) {
  return (
    <aside className="flex h-screen w-64 shrink-0 flex-col bg-[#304156] lg:w-50">
      <div className="h-15 leading-15 text-center text-white text-lg font-bold border-b border-[#1f2d3d]">
        教务管理系统
      </div>
      <nav className="flex-1 overflow-y-auto py-2">
        {menus.map((menu) => {
          const isActive = activePath === menu.path;
          return (
            <Link
              key={menu.path}
              to={menu.path}
              onClick={onNavigate}
              className={`block px-5 py-3 text-sm transition-colors
                ${isActive ? "text-[#409EFF]" : "text-[#bfcbd9] hover:text-white"}`}
            >
              {menu.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
