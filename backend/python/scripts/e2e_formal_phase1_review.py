#!/usr/bin/env python3
"""Phase-1 acceptance checks 4, 5 and 8 from docs/implementation/10.

Reuses the fixture and generation helpers from scripts/e2e_formal_phase1.py.
Checks 2/3/6/7 are already covered by that script; this one adds:
  4  exact-week narrowing makes the hour audit UNDER, restoring it re-balances
  5  hour tails can be accepted with a reason, hard problems can never be,
     and an acceptance expires as soon as the draft changes
  8  runtime time-slot edits, legacy scheme bypass, confirmed master-data
     edits and duplicate confirmation are all refused
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import e2e_formal_phase1 as e2e  # noqa: E402

RESULTS: list[dict[str, Any]] = []


def record(check: str, name: str, ok: bool, detail: Any = None) -> None:
    RESULTS.append({"check": check, "name": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {check} {name}" + (f" :: {detail}" if detail else ""))


def expect_reject(method: str, path: str, payload: dict | None = None) -> str:
    """Return the rejection message, or raise if the call unexpectedly succeeded."""
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = Request(e2e.API_BASE + path, data=body, method=method,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            envelope = json.load(response)
    except HTTPError as exc:
        return f"HTTP {exc.code}: {exc.read().decode()[:200]}"
    if envelope.get("code") != 0:
        return json.dumps(envelope, ensure_ascii=False)[:200]
    raise AssertionError(f"{method} {path} was accepted but should have been refused")


def week_entries(task_id: int, week: int) -> list[dict]:
    return e2e.api("GET", f"/api/allocation-tasks/{task_id}/templates/weeks/{week}/timetable")


def draft(scheme_id: int) -> dict:
    return e2e.api("GET", f"/api/allocation-schemes/{scheme_id}/template-draft")


def main() -> None:
    label = f"x{int(time.time())}-{os.getpid()}"
    fixture = e2e.create_fixture(label)
    task_id = fixture["allocationTask"]
    theory_task = fixture["theoryTask"]
    e2e.wait_for_generation(task_id)
    schemes = e2e.api("GET", f"/api/allocation-tasks/{task_id}/schemes")
    scheme_id = int(schemes[0]["id"])

    view = draft(scheme_id)
    base_audit = view["audit"]
    record("setup", "generated draft is balanced",
           base_audit["valid"] and base_audit["deltaTotalHours"] == 0,
           {"required": base_audit["requiredTotalHours"], "scheduled": base_audit["scheduledTotalHours"]})

    # ---- Check 4: narrow a fragment to one exact week ----------------------
    entries = week_entries(task_id, 1)
    theory = next(e for e in entries if e["teachingTaskId"] == theory_task)
    fragment_id = theory["templateFragmentId"]
    template_id = theory["templateId"]
    original_weeks = sorted({
        w for w in range(1, 7)
        if any(x["templateFragmentId"] == fragment_id for x in week_entries(task_id, w))
    })
    record("4", "fragment starts on multiple weeks", len(original_weeks) > 1, original_weeks)

    narrowed = e2e.api("PUT", f"/api/allocation-schemes/{scheme_id}/template-fragments/{fragment_id}", {
        "templateId": template_id, "teachingTaskId": theory_task,
        "classroomId": theory["classroomId"], "dayOfWeek": theory["dayOfWeek"],
        "periodIndex": theory["periodIndex"], "consecutiveSlots": theory["consecutiveSlots"],
        "weekNumbers": [original_weeks[0]], "reason": "acceptance check 4",
    })
    still_present = [w for w in original_weeks[1:]
                     if any(x["templateFragmentId"] == fragment_id for x in week_entries(task_id, w))]
    record("4", "other weeks disappear", still_present == [], {"stillPresent": still_present})
    record("4", "hour audit turns UNDER",
           narrowed["audit"]["deltaTotalHours"] < 0 and narrowed["audit"]["hourMismatchTaskCount"] >= 1,
           {"delta": narrowed["audit"]["deltaTotalHours"]})

    # ---- Check 5: accept an hour tail, never a hard problem ----------------
    review_state = narrowed["audit"]["reviewStatus"]
    record("5", "under-scheduled draft is not COMPLETE", review_state != "COMPLETE", review_state)

    accepted = e2e.api("POST", f"/api/allocation-schemes/{scheme_id}/manual-review-acceptance",
                       {"reason": "acceptance check 5: registrar accepts the hour tail"})
    record("5", "hour tail can be accepted with a written reason",
           accepted["audit"]["reviewStatus"] != review_state,
           {"before": review_state, "after": accepted["audit"]["reviewStatus"]})

    # Deliberately collide with the fragment that is still on week 1.
    before_ids = {e["templateFragmentId"] for e in week_entries(task_id, original_weeks[0])}
    conflicted = e2e.api("POST", f"/api/allocation-schemes/{scheme_id}/template-fragments", {
        "templateId": template_id, "teachingTaskId": theory_task,
        "classroomId": theory["classroomId"], "dayOfWeek": theory["dayOfWeek"],
        "periodIndex": theory["periodIndex"], "consecutiveSlots": theory["consecutiveSlots"],
        "weekNumbers": [original_weeks[0]], "reason": "deliberate hard conflict",
    })
    record("5", "hard conflict is detected and blocks the draft",
           conflicted["audit"]["reviewStatus"] == "BLOCKED"
           and not conflicted["audit"]["valid"]
           and conflicted["audit"]["hardConflictCount"] > 0,
           {"reviewStatus": conflicted["audit"]["reviewStatus"],
            "hardConflicts": conflicted["audit"]["hardConflictCount"],
            "firstIssue": conflicted["audit"]["issues"][0] if conflicted["audit"]["issues"] else None})
    record("5", "a hard problem can never be accepted", True,
           expect_reject("POST", f"/api/allocation-schemes/{scheme_id}/manual-review-acceptance",
                         {"reason": "试图豁免硬冲突"}))
    record("5", "a blocked draft cannot be confirmed", True,
           expect_reject("POST", f"/api/allocation-schemes/{scheme_id}/confirm", {}))

    after_ids = {e["templateFragmentId"] for e in week_entries(task_id, original_weeks[0])}
    added = sorted(after_ids - before_ids)
    record("5", "the conflicting fragment is identifiable", len(added) == 1, added)
    cleared = e2e.api(
        "DELETE",
        f"/api/allocation-schemes/{scheme_id}/template-fragments/{added[0]}?reason=remove+conflict",
    )
    record("5", "removing it clears the hard conflict",
           cleared["audit"]["hardConflictCount"] == 0, cleared["audit"]["reviewStatus"])
    record("5", "the earlier acceptance expired once the draft changed",
           cleared["audit"]["reviewStatus"] != "COMPLETE"
           and cleared["audit"]["deltaTotalHours"] < 0,
           {"reviewStatus": cleared["audit"]["reviewStatus"],
            "delta": cleared["audit"]["deltaTotalHours"]})

    restored = e2e.api("PUT", f"/api/allocation-schemes/{scheme_id}/template-fragments/{fragment_id}", {
        "templateId": template_id, "teachingTaskId": theory_task,
        "classroomId": theory["classroomId"], "dayOfWeek": theory["dayOfWeek"],
        "periodIndex": theory["periodIndex"], "consecutiveSlots": theory["consecutiveSlots"],
        "weekNumbers": original_weeks, "reason": "acceptance check 4 restore",
    })
    record("4", "restoring the weeks re-balances the audit",
           restored["audit"]["deltaTotalHours"] == 0
           and restored["audit"]["hourMismatchTaskCount"] == 0
           and restored["audit"]["reviewStatus"] == "COMPLETE",
           {"delta": restored["audit"]["deltaTotalHours"],
            "reviewStatus": restored["audit"]["reviewStatus"]})

    # ---- Check 8: bypasses are refused ------------------------------------
    record("8", "time_slot catalog is read-only at runtime", True,
           expect_reject("PUT", "/api/time-slots/1",
                         {"weekNumber": 1, "dayOfWeek": 1, "periodIndex": 1}))
    record("8", "time_slot cannot be deleted at runtime", True,
           expect_reject("DELETE", "/api/time-slots/1"))

    confirmation = e2e.api("POST", f"/api/allocation-schemes/{scheme_id}/confirm", {})
    record("8", "confirmation materialises the formal timetable",
           confirmation["assignmentCount"] > 0, confirmation)

    record("8", "duplicate confirmation is refused", True,
           expect_reject("POST", f"/api/allocation-schemes/{scheme_id}/confirm", {}))
    record("8", "legacy scheme delete is refused", True,
           expect_reject("DELETE", f"/api/allocation-schemes/{scheme_id}"))
    record("8", "teacher referenced by a published timetable is frozen", True,
           expect_reject("PUT", f"/api/teachers/{fixture['primary']}",
                         {"employeeNo": f"E2E-P-{label}", "name": "改名尝试",
                          "department": "计算机学院", "title": "讲师", "status": "ACTIVE"}))
    record("8", "classroom referenced by a published timetable is frozen", True,
           expect_reject("PUT", f"/api/classrooms/{fixture['fixedRoom']}",
                         {"name": f"E2E-A101-{label}", "building": "A楼", "capacity": 10,
                          "classroomType": "普通教室", "status": "ACTIVE"}))
    record("8", "teaching task referenced by a published timetable is frozen", True,
           expect_reject("DELETE", f"/api/teaching-tasks/{theory_task}"))

    failed = [r for r in RESULTS if not r["ok"]]
    print("\n" + json.dumps({"total": len(RESULTS), "failed": len(failed),
                             "results": RESULTS}, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
