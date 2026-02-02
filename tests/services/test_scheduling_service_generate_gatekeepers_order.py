"""
Generate gatekeepers order tests.

We verify the strict order inside SchedulingService.generate():

1) feasibility precheck runs first
   -> if it returns issues, we raise generate_requires_ignore
   -> head conflicts check MUST NOT run
   -> solver MUST NOT run

2) head commitment conflicts check runs second
   -> only if precheck is clean
   -> if conflicts exist, we raise generate_requires_head_resolution
   -> solver MUST NOT run

3) solver runs only if both gatekeepers pass
   -> we detect this by a sentinel exception thrown from a stubbed solver
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.core.types import FeasibilityIssue, ProblemData
from backend.models.common_enums import ShiftType
from backend.models.schemas.schedule import ScheduleGenerateRequest
from backend.services import scheduling_service
from backend.services.errors import DomainError
from backend.services.scheduling_service import SchedulingService


def _minimal_problem(*, year: int, month: int) -> ProblemData:
    """
    Build a minimal ProblemData object for tests.

    We do NOT touch the DB here. The service opens a DB session anyway,
    but we patch _build_problem_data_for_generate() to return this object.
    """
    return ProblemData(
        year=int(year),
        month=int(month),
        days=[1],
        weekdays={1: 0},
        doctors={},
        preferences={},
        participant_doctor_ids=set(),  # empty is fine for gatekeepers
        ignore_slots=set(),
    )


def _minimal_req(*, year: int, month: int) -> ScheduleGenerateRequest:
    """
    Minimal generate request DTO.
    """
    return ScheduleGenerateRequest(
        year=int(year),
        month=int(month),
        participant_doctor_ids=[],
        ignore_slots=[],
        head_commitment_resolutions=[],
    )


def test_generate_precheck_blocks_before_head_conflicts_and_solver(monkeypatch):
    """
    If feasibility precheck returns issues:
    - raise DomainError("generate_requires_ignore")
    - do NOT check head conflicts
    - do NOT call solver
    """
    svc = SchedulingService()
    req = _minimal_req(year=2026, month=2)

    # 1) Patch problem builder to avoid DB reads.
    monkeypatch.setattr(
        scheduling_service,
        "_build_problem_data_for_generate",
        lambda session, req: _minimal_problem(year=req.year, month=req.month),
    )

    # 2) Precheck returns a blocking issue.
    def _fake_precheck(problem: ProblemData) -> List[FeasibilityIssue]:
        return [FeasibilityIssue(day=3, code="no_specialist", message="No specialist available.")]

    monkeypatch.setattr(scheduling_service.core_feasibility, "analyze_problem", _fake_precheck)

    # 3) Head conflicts must NOT run if precheck blocks.
    def _must_not_run(_problem: ProblemData) -> List[Dict[str, Any]]:
        raise AssertionError("head conflicts check must not run when precheck blocks")

    monkeypatch.setattr(scheduling_service, "_detect_head_commitment_conflicts", _must_not_run)

    # 4) Solver must NOT run.
    import backend.core.scheduler as scheduler_mod

    def _solver_must_not_run(_problem: ProblemData):
        raise AssertionError("solver must not run when precheck blocks")

    monkeypatch.setattr(scheduler_mod, "generate_schedule", _solver_must_not_run)

    with pytest.raises(DomainError) as ex:
        svc.generate(req, user_id=1)

    assert str(ex.value) == "generate_requires_ignore"
    assert isinstance(ex.value.context, dict)
    assert ex.value.context.get("issues_total") == 1


def test_generate_head_conflicts_block_before_solver(monkeypatch):
    """
    If precheck passes but head conflicts exist:
    - raise DomainError("generate_requires_head_resolution")
    - solver is NOT called
    """
    svc = SchedulingService()
    req = _minimal_req(year=2026, month=2)

    monkeypatch.setattr(
        scheduling_service,
        "_build_problem_data_for_generate",
        lambda session, req: _minimal_problem(year=req.year, month=req.month),
    )

    # Precheck passes.
    monkeypatch.setattr(scheduling_service.core_feasibility, "analyze_problem", lambda problem: [])

    # Head conflicts exist (head_ids empty -> service will skip DB lookup for names).
    monkeypatch.setattr(
        scheduling_service,
        "_detect_head_commitment_conflicts",
        lambda _problem: [{"day": 3, "shift_type": ShiftType.onsite.value, "head_ids": []}],
    )

    # Solver must NOT run.
    import backend.core.scheduler as scheduler_mod

    def _solver_must_not_run(_problem: ProblemData):
        raise AssertionError("solver must not run when head conflicts exist")

    monkeypatch.setattr(scheduler_mod, "generate_schedule", _solver_must_not_run)

    with pytest.raises(DomainError) as ex:
        svc.generate(req, user_id=1)

    assert str(ex.value) == "generate_requires_head_resolution"
    assert isinstance(ex.value.context, dict)
    conflicts = ex.value.context.get("head_commitment_conflicts")
    assert isinstance(conflicts, list)
    assert conflicts and conflicts[0].get("day") == 3


def test_generate_calls_solver_only_when_gatekeepers_pass(monkeypatch):
    """
    If both gatekeepers pass:
    - we should reach the solver call.
    We detect this by making the solver raise ValueError("sentinel_solver_called").
    """
    svc = SchedulingService()
    req = _minimal_req(year=2026, month=2)

    monkeypatch.setattr(
        scheduling_service,
        "_build_problem_data_for_generate",
        lambda session, req: _minimal_problem(year=req.year, month=req.month),
    )

    monkeypatch.setattr(scheduling_service.core_feasibility, "analyze_problem", lambda problem: [])
    monkeypatch.setattr(scheduling_service, "_detect_head_commitment_conflicts", lambda _problem: [])

    import backend.core.scheduler as scheduler_mod

    def _solver_sentinel(_problem: ProblemData):
        # This proves we reached solver call without having to go through DB writes.
        raise ValueError("sentinel_solver_called")

    monkeypatch.setattr(scheduler_mod, "generate_schedule", _solver_sentinel)

    with pytest.raises(ValueError) as ex:
        svc.generate(req, user_id=1)

    assert str(ex.value) == "sentinel_solver_called"
