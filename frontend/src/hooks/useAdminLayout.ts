import { useAtomValue, useSetAtom } from "jotai";
import { useNavigate, useLocation } from "@tanstack/react-router";
import { displayNameAtom, isAdminAtom, tokenAtom, userAtom } from "../atoms/auth";

interface MenuItem {
  path: string;
  label: string;
}

const menus: MenuItem[] = [
  { path: "/admin", label: "首页" },
  { path: "/admin/classrooms", label: "教室管理" },
  { path: "/admin/courses", label: "课程管理" },
  { path: "/admin/class-groups", label: "班级管理" },
  { path: "/admin/teachers", label: "教师管理" },
  { path: "/admin/teaching-tasks", label: "教学任务" },
  { path: "/admin/simulation", label: "模拟实验台" },
  { path: "/admin/import-review", label: "导入审核" },
  { path: "/admin/allocation", label: "分课任务" },
  { path: "/admin/model-training", label: "模型训练" },
  { path: "/admin/teacher-profiles", label: "教师画像" },
  { path: "/admin/timetable", label: "课表查询" },
  { path: "/admin/adjustment", label: "调课处理" },
  { path: "/admin/constraint-editor", label: "约束干预" },
];

export function useAdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const displayName = useAtomValue(displayNameAtom);
  const isAdmin = useAtomValue(isAdminAtom);
  const setToken = useSetAtom(tokenAtom);
  const setUser = useSetAtom(userAtom);

  const role = isAdmin ? "管理员" : "教师";

  function handleLogout() {
    setToken(null);
    setUser(null);
    navigate({ to: "/login" });
  }

  return {
    menus,
    activePath: location.pathname,
    displayName,
    role,
    handleLogout,
  };
}
