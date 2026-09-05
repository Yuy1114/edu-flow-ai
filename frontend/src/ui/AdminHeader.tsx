interface AdminHeaderProps {
  displayName: string;
  role: string;
  onLogout: () => void;
  onMenuOpen: () => void;
}

export default function AdminHeader({
  displayName,
  role,
  onLogout,
  onMenuOpen,
}: AdminHeaderProps) {
  return (
    <header className="flex h-15 shrink-0 items-center justify-between border-b border-gray-700 bg-gray-800 px-3 shadow-sm sm:px-5">
      <div className="flex items-center gap-3"><button className="btn btn-ghost btn-sm px-2 text-gray-100 lg:hidden" aria-label="打开导航" onClick={onMenuOpen}>☰</button><span className="text-sm font-medium text-gray-100 sm:text-base">教务管理员端</span></div>
      <div className="flex items-center gap-2 sm:gap-4">
        <span className="hidden text-gray-300 sm:inline">{displayName}</span>
        <span className="badge badge-success badge-sm sm:badge-md">{role}</span>
        <button className="btn btn-error btn-sm" onClick={onLogout}>
          退出
        </button>
      </div>
    </header>
  );
}
