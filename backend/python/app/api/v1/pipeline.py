"""Durable asynchronous entry point for the formal scheduling pipeline."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.db.session import connect, load_db_config

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

RESULT_PREFIX = "EDUFLOW_PIPELINE_RESULT="
ACTIVE_STATUSES = ("QUEUED", "RUNNING")
GENERATABLE_ALLOCATION_TASK_STATUSES = frozenset({
    "CREATED", "DRAFT", "PENDING", "FAILED", "BLOCKED",
})
TERMINAL_STATUS_BY_PIPELINE = {
    "OK": "SUCCESS",
    "NEEDS_MANUAL_REVIEW": "NEEDS_MANUAL_REVIEW",
    "BLOCKED": "BLOCKED",
}
STATUS_MESSAGES = {
    "NEEDS_MANUAL_REVIEW": "自动排课已生成可查看候选，但存在未排任务或课时差异，需要人工复核",
    "BLOCKED": "排课产物未通过资源引用、硬冲突或落库校验，已阻止发布",
}
ALLOCATION_TASK_STATUS_BY_JOB = {
    "QUEUED": "RUNNING",
    "RUNNING": "RUNNING",
    "SUCCESS": "GENERATED",
    "NEEDS_MANUAL_REVIEW": "NEEDS_MANUAL_REVIEW",
    "BLOCKED": "BLOCKED",
    "FAILED": "FAILED",
}
PIPELINE_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = Path(os.environ.get("EDU_FLOW_PIPELINE_LOG_DIR", "/tmp/edu-flow-ai-pipeline-jobs"))
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("EDU_FLOW_PIPELINE_TIMEOUT_SECONDS", "1800"))

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="formal-scheduling-pipeline")
_submission_lock = threading.Lock()


class PipelineJobRequest(BaseModel):
    allocationTaskId: int = Field(gt=0)
    # The canonical time_slot catalog is deliberately fixed to an 18-week
    # semester in Phase 1.  Accepting later weeks here would let generation
    # succeed with coordinates that confirmation cannot materialize.
    totalWeeks: int = Field(default=18, ge=1, le=18)
    topK: int = Field(default=300, ge=1, le=1000)
    maxTemplates: int = Field(default=8, ge=1, le=100)
    trainModel: bool = False
    importDb: bool = True
    truncateDb: bool = False
    timeoutSeconds: int = Field(default=DEFAULT_TIMEOUT_SECONDS, ge=30, le=7200)


class PipelineJobStatus(BaseModel):
    status: str
    startedAt: int | None = None
    progress: int = 0
    error: str | None = None
    jobId: str | None = None
    finishedAt: int | None = None
    summaryPath: str | None = None


def initialize_pipeline_worker() -> int:
    """Recover committed results and fail only genuinely unfinished jobs.

    The child pipeline commits its candidate in one transaction before emitting
    the terminal sentinel.  A process restart in the tiny interval after that
    commit must not strand a valid candidate behind a FAILED task that can no
    longer be regenerated.
    """
    now = _now_ms()
    connection = connect(load_db_config())
    try:
        connection.begin()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, allocation_task_id, log_path
                FROM schedule_generation_run
                WHERE status IN ('QUEUED', 'RUNNING')
                ORDER BY created_at_ms
                FOR UPDATE
                """
            )
            interrupted = list(cursor.fetchall())
            for run in interrupted:
                cursor.execute(
                    """
                    SELECT valid, status
                    FROM allocation_scheme
                    WHERE task_id = %s AND status IN ('CANDIDATE', 'CONFIRMED')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (run["allocation_task_id"],),
                )
                candidate = cursor.fetchone()
                recovered = _recover_interrupted_run(run, candidate)
                cursor.execute(
                    """
                    UPDATE schedule_generation_run
                    SET status = %s, pipeline_status = %s, progress = 100,
                        finished_at_ms = %s, active_allocation_task_id = NULL,
                        summary_path = %s, error_message = %s
                    WHERE id = %s AND status IN ('QUEUED', 'RUNNING')
                    """,
                    (
                        recovered["status"], recovered["pipeline_status"], now,
                        recovered["summary_path"], recovered["error_message"], run["id"],
                    ),
                )
                cursor.execute(
                    """
                    UPDATE allocation_task
                    SET status = %s
                    WHERE id = %s
                      AND status NOT IN ('CONFIRMED', 'CANCELLED', 'REJECTED')
                    """,
                    (_allocation_task_status(recovered["status"]), run["allocation_task_id"]),
                )
        connection.commit()
        return len(interrupted)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _recover_interrupted_run(
    run: dict[str, Any],
    candidate: dict[str, Any] | None,
) -> dict[str, str | None]:
    """Derive a durable terminal state without inventing a scheduling result."""
    log_path = _optional_string(run.get("log_path"))
    if log_path:
        try:
            result = _parse_pipeline_result(Path(log_path))
            pipeline_status = str(result.get("status") or "")
            terminal_status = TERMINAL_STATUS_BY_PIPELINE.get(pipeline_status)
            if terminal_status is not None:
                summary_path = _optional_string(result.get("summary"))
                return {
                    "status": terminal_status,
                    "pipeline_status": pipeline_status,
                    "summary_path": summary_path,
                    "error_message": _pipeline_terminal_error(
                        terminal_status, result, summary_path,
                    ),
                }
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
            # A truncated log is not a result.  A committed candidate below is
            # still authoritative because draft + scheme insertion is atomic.
            pass

    if candidate is not None:
        candidate_valid = bool(candidate.get("valid"))
        terminal_status = "SUCCESS" if candidate_valid else "NEEDS_MANUAL_REVIEW"
        pipeline_status = "OK" if candidate_valid else "NEEDS_MANUAL_REVIEW"
        return {
            "status": terminal_status,
            "pipeline_status": pipeline_status,
            "summary_path": None,
            "error_message": None if candidate_valid else (
                "排课工作进程在候选方案提交后重启；已恢复候选方案，请继续人工复核"
            ),
        }

    return {
        "status": "FAILED",
        "pipeline_status": None,
        "summary_path": None,
        "error_message": "排课工作进程重启，上一次未完成任务已终止，请重新发起",
    }


@router.post("/jobs", response_model=PipelineJobStatus, status_code=status.HTTP_202_ACCEPTED)
def submit_pipeline_job(request: PipelineJobRequest) -> PipelineJobStatus:
    _validate_formal_request(request)
    with _submission_lock:
        job_id = f"pipeline-{uuid.uuid4().hex}"
        created_at = _now_ms()
        log_path = LOG_DIR / f"{job_id}.log"
        row = {
            "id": job_id,
            "allocation_task_id": request.allocationTaskId,
            "status": "QUEUED",
            "pipeline_status": None,
            "progress": 0,
            "timeout_seconds": request.timeoutSeconds,
            "request_json": request.model_dump_json(),
            "log_path": str(log_path),
            "summary_path": None,
            "error_message": None,
            "created_at_ms": created_at,
            "started_at_ms": None,
            "finished_at_ms": None,
        }
        existing = _reserve_job(row)
        if existing is not None:
            return _to_status(existing)
        try:
            _executor.submit(_execute_job, job_id, request, log_path)
        except Exception as exc:
            _finish_job(job_id, status_value="FAILED", error=f"worker submission failed: {exc}")
            raise HTTPException(status_code=503, detail="pipeline worker is unavailable") from exc
        return _to_status(row)


@router.get("/jobs/latest", response_model=PipelineJobStatus)
def latest_pipeline_job(allocation_task_id: int = Query(gt=0)) -> PipelineJobStatus:
    row = _find_latest_job(allocation_task_id)
    if row is None:
        return PipelineJobStatus(status="IDLE", progress=0)
    return _to_status(row)


@router.get("/jobs/{job_id}", response_model=PipelineJobStatus)
def get_pipeline_job(job_id: str) -> PipelineJobStatus:
    row = _find_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="pipeline job not found")
    return _to_status(row)


def _validate_formal_request(request: PipelineJobRequest) -> None:
    if not request.importDb:
        raise HTTPException(status_code=422, detail="formal scheduling requires importDb=true")
    if request.truncateDb:
        raise HTTPException(status_code=422, detail="formal scheduling never truncates shared template tables")
    if request.trainModel:
        raise HTTPException(status_code=422, detail="Phase 1 formal scheduling is rules-only; trainModel must be false")


def _pipeline_command(request: PipelineJobRequest) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scheduler.run_pipeline",
        "--allocation-task-id",
        str(request.allocationTaskId),
        "--total-weeks",
        str(request.totalWeeks),
        "--top-k",
        str(request.topK),
        "--max-templates",
        str(request.maxTemplates),
        "--import-db",
    ]


def _execute_job(job_id: str, request: PipelineJobRequest, log_path: Path) -> None:
    started_at = _now_ms()
    _update_job(
        job_id,
        status_value="RUNNING",
        progress=10,
        started_at_ms=started_at,
        error_message=None,
    )
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    process: subprocess.Popen[str] | None = None
    try:
        with log_path.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                _pipeline_command(request),
                cwd=PIPELINE_ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=request.timeoutSeconds)
            except subprocess.TimeoutExpired as exc:
                _terminate_process_group(process)
                raise TimeoutError(
                    f"排课任务超过 {request.timeoutSeconds} 秒上限，已强制终止"
                ) from exc

        if exit_code != 0:
            raise RuntimeError(f"pipeline exited with code {exit_code}: {_log_tail(log_path)}")

        result = _parse_pipeline_result(log_path)
        pipeline_status = str(result.get("status") or "")
        terminal_status = TERMINAL_STATUS_BY_PIPELINE.get(pipeline_status)
        if terminal_status is None:
            raise RuntimeError(f"unknown pipeline terminal status: {pipeline_status or '<empty>'}")
        summary_path = _optional_string(result.get("summary"))
        _finish_job(
            job_id,
            status_value=terminal_status,
            pipeline_status=pipeline_status,
            summary_path=summary_path,
            error=_pipeline_terminal_error(terminal_status, result, summary_path),
        )
    except Exception as exc:
        if process is not None and process.poll() is None:
            _terminate_process_group(process)
        _finish_failed_or_recover(
            job_id,
            allocation_task_id=request.allocationTaskId,
            log_path=log_path,
            original_error=str(exc)[:2000],
        )


def _finish_failed_or_recover(
    job_id: str,
    *,
    allocation_task_id: int,
    log_path: Path,
    original_error: str,
) -> None:
    """Do not strand a candidate committed just before a worker failure.

    Draft templates and their candidate scheme are committed atomically.  The
    child may still fail while writing its summary or terminal sentinel.  In
    that narrow window FAILED would be incorrect and would also make a retry
    impossible because the task already owns a candidate.
    """
    try:
        candidate = _find_candidate(allocation_task_id)
        recovered = _recover_interrupted_run(
            {"log_path": str(log_path)},
            candidate,
        )
    except Exception:
        # Recovery is best-effort; preserve the original process failure when
        # the database/log cannot be inspected.
        _finish_job(job_id, status_value="FAILED", error=original_error)
        return

    recovered_status = str(recovered["status"] or "FAILED")
    if recovered_status == "FAILED":
        _finish_job(job_id, status_value="FAILED", error=original_error)
        return
    _finish_job(
        job_id,
        status_value=recovered_status,
        pipeline_status=_optional_string(recovered.get("pipeline_status")),
        summary_path=_optional_string(recovered.get("summary_path")),
        error=_optional_string(recovered.get("error_message")),
    )


def _find_candidate(allocation_task_id: int) -> dict[str, Any] | None:
    return _fetch_one(
        """
        SELECT valid, status
        FROM allocation_scheme
        WHERE task_id = %s AND status IN ('CANDIDATE', 'CONFIRMED')
        ORDER BY id DESC LIMIT 1
        """,
        (allocation_task_id,),
    )


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def _parse_pipeline_result(log_path: Path) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(RESULT_PREFIX):
            payload = json.loads(line[len(RESULT_PREFIX):])
            if not isinstance(payload, dict):
                raise ValueError("pipeline result must be a JSON object")
            result = payload
    if result is None:
        raise RuntimeError("pipeline did not emit EDUFLOW_PIPELINE_RESULT")
    return result


def _log_tail(path: Path, limit: int = 2000) -> str:
    if not path.exists():
        return "no pipeline log"
    return path.read_text(encoding="utf-8", errors="replace")[-limit:]


def _pipeline_terminal_error(
    terminal_status: str,
    result: dict[str, Any],
    summary_path: str | None,
    *,
    reason_limit: int = 10,
) -> str | None:
    """Return user-visible blockers; container-local summary paths are not enough."""
    if terminal_status == "SUCCESS":
        return None
    publication_gate = result.get("publication_gate")
    if not isinstance(publication_gate, dict) and summary_path:
        try:
            summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
            publication_gate = summary.get("publication_gate")
        except (OSError, json.JSONDecodeError):
            publication_gate = None
    gate = publication_gate if isinstance(publication_gate, dict) else {}
    reason_key = "hard_blockers" if terminal_status == "BLOCKED" else "manual_reviews"
    reasons = [str(reason).strip() for reason in (gate.get(reason_key) or []) if str(reason).strip()]
    message = STATUS_MESSAGES.get(terminal_status)
    if not reasons:
        return message
    visible = reasons[:reason_limit]
    suffix = f"；另有 {len(reasons) - reason_limit} 项" if len(reasons) > reason_limit else ""
    detail = "；".join(visible) + suffix
    return f"{message}。具体原因：{detail}" if message else detail


def _reserve_job(row: dict[str, Any]) -> dict[str, Any] | None:
    """Lock the task, validate its lifecycle, and reserve one active run atomically."""
    connection = connect(load_db_config())
    try:
        connection.begin()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM allocation_task WHERE id = %s FOR UPDATE",
                (row["allocation_task_id"],),
            )
            task = cursor.fetchone()
            if task is None:
                raise HTTPException(status_code=404, detail="allocation task not found")
            cursor.execute(
                """
                SELECT * FROM schedule_generation_run
                WHERE allocation_task_id = %s AND status IN ('QUEUED', 'RUNNING')
                ORDER BY created_at_ms DESC LIMIT 1
                """,
                (row["allocation_task_id"],),
            )
            existing = cursor.fetchone()
            if existing is not None:
                connection.commit()
                return existing
            task_status = str(task.get("status") or "")
            if task_status not in GENERATABLE_ALLOCATION_TASK_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail=f"allocation task status {task_status or '<empty>'} cannot start generation",
                )
            cursor.execute(
                "SELECT COUNT(*) AS count FROM allocation_scheme WHERE task_id = %s",
                (row["allocation_task_id"],),
            )
            if int(cursor.fetchone()["count"] or 0) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="allocation task already has candidate schemes; create a new task to regenerate",
                )
            cursor.execute(
                """
                INSERT INTO schedule_generation_run (
                    id, allocation_task_id, status, pipeline_status, progress,
                    timeout_seconds, request_json, log_path, summary_path,
                    error_message, created_at_ms, started_at_ms, finished_at_ms,
                    active_allocation_task_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                tuple(row[key] for key in (
                    "id", "allocation_task_id", "status", "pipeline_status", "progress",
                    "timeout_seconds", "request_json", "log_path", "summary_path",
                    "error_message", "created_at_ms", "started_at_ms", "finished_at_ms",
                )) + (row["allocation_task_id"],),
            )
            cursor.execute(
                "UPDATE allocation_task SET status = 'RUNNING' WHERE id = %s",
                (row["allocation_task_id"],),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"allocation task disappeared: {row['allocation_task_id']}"
                )
        connection.commit()
        return None
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _update_job(
    job_id: str,
    *,
    status_value: str,
    progress: int,
    started_at_ms: int | None = None,
    pipeline_status: str | None = None,
    summary_path: str | None = None,
    error_message: str | None = None,
    finished_at_ms: int | None = None,
) -> None:
    connection = connect(load_db_config())
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE schedule_generation_run
                SET status = %s, progress = %s,
                    active_allocation_task_id = CASE
                        WHEN %s IN ('QUEUED', 'RUNNING') THEN allocation_task_id ELSE NULL
                    END,
                    started_at_ms = COALESCE(%s, started_at_ms),
                    pipeline_status = %s, summary_path = %s,
                    error_message = %s, finished_at_ms = %s
                WHERE id = %s
                """,
                (
                    status_value, progress, status_value, started_at_ms, pipeline_status,
                    summary_path, error_message, finished_at_ms, job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"pipeline job disappeared: {job_id}")
            task_status = _allocation_task_status(status_value)
            cursor.execute(
                """
                UPDATE allocation_task task
                JOIN schedule_generation_run run ON run.allocation_task_id = task.id
                SET task.status = %s
                WHERE run.id = %s
                  AND task.status NOT IN ('CONFIRMED', 'CANCELLED', 'REJECTED')
                """,
                (task_status, job_id),
            )
            if cursor.rowcount not in (0, 1):
                raise RuntimeError(f"unexpected allocation task update count for job: {job_id}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _finish_job(
    job_id: str,
    *,
    status_value: str,
    error: str | None,
    pipeline_status: str | None = None,
    summary_path: str | None = None,
) -> None:
    _update_job(
        job_id,
        status_value=status_value,
        progress=100,
        pipeline_status=pipeline_status,
        summary_path=summary_path,
        error_message=error,
        finished_at_ms=_now_ms(),
    )


def _find_job(job_id: str) -> dict[str, Any] | None:
    return _fetch_one(
        "SELECT * FROM schedule_generation_run WHERE id = %s",
        (job_id,),
    )


def _find_active_job(allocation_task_id: int) -> dict[str, Any] | None:
    return _fetch_one(
        """
        SELECT * FROM schedule_generation_run
        WHERE allocation_task_id = %s AND status IN ('QUEUED', 'RUNNING')
        ORDER BY created_at_ms DESC LIMIT 1
        """,
        (allocation_task_id,),
    )


def _find_latest_job(allocation_task_id: int) -> dict[str, Any] | None:
    return _fetch_one(
        """
        SELECT * FROM schedule_generation_run
        WHERE allocation_task_id = %s
        ORDER BY created_at_ms DESC LIMIT 1
        """,
        (allocation_task_id,),
    )


def _fetch_one(sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    connection = connect(load_db_config())
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()
    finally:
        connection.close()


def _to_status(row: dict[str, Any]) -> PipelineJobStatus:
    return PipelineJobStatus(
        status=str(row.get("status") or "FAILED"),
        startedAt=_optional_int(row.get("started_at_ms")),
        progress=int(row.get("progress") or 0),
        error=_optional_string(row.get("error_message")),
        jobId=_optional_string(row.get("id")),
        finishedAt=_optional_int(row.get("finished_at_ms")),
        summaryPath=_optional_string(row.get("summary_path")),
    )


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_string(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _allocation_task_status(job_status: str) -> str:
    try:
        return ALLOCATION_TASK_STATUS_BY_JOB[job_status]
    except KeyError as exc:
        raise ValueError(f"unknown durable pipeline job status: {job_status}") from exc
