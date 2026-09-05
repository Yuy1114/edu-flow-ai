import { useTeachingTasks } from "../hooks/useTeachingTasks";
import TeachingTaskTable from "../ui/TeachingTaskTable";
import TeachingTaskDialog from "../ui/TeachingTaskDialog";

export default function TeachingTaskManager() {
  const t = useTeachingTasks();
  return (
    <>
      <TeachingTaskTable tasks={t.paged} loading={t.loading} search={t.search} onSearchChange={t.setSearch} courseTypeFilter={t.courseTypeFilter} onCourseTypeFilterChange={t.setCourseTypeFilter} taskBatchFilter={t.taskBatchFilter} taskBatchOptions={t.taskBatchOptions} onTaskBatchFilterChange={t.setTaskBatchFilter} statusFilter={t.statusFilter} onStatusFilterChange={t.setStatusFilter} page={t.page} pageSize={t.pageSize} total={t.filtered.length} onPageChange={t.setPage} onPageSizeChange={t.setPageSize} deleting={t.deleting} onEdit={t.openDialog} onDelete={t.remove} onAdd={() => t.openDialog()} batch={t.batch} />
      {t.dialogOpen && <TeachingTaskDialog form={t.form} onChange={t.setForm} saving={t.saving} onSave={t.save} onClose={t.closeDialog} courses={t.courses} teachers={t.teachers} classGroups={t.classGroups} classrooms={t.classrooms} onCourseChanged={t.onCourseChanged} />}
    </>
  );
}
