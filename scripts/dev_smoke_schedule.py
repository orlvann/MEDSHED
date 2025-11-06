"""
Dev smoke for SchedulingService:
generate → publish → publish → revert(prev) → revert(next).

Goal:
- Quick manual sanity-check of the service without pytest.
- Prints compact summaries to the console.

Run:
    python -m scripts.dev_smoke_schedule
"""

from __future__ import annotations

from datetime import datetime, timezone  # use timezone-aware UTC
from pprint import pprint as pp

from backend.models.schemas.schedule import (
    ScheduleGenerateRequest,
    SchedulePublishedRevertRead,
)
from backend.services.scheduling_service import SchedulingService


def main() -> None:
    # Use current month for convenience in dev.
    now = datetime.now(timezone.utc)  # timezone-aware UTC datetime

    year, month = now.year, now.month

    svc = SchedulingService()

    print("\n=== GENERATE ===")
    gen = svc.generate(
        ScheduleGenerateRequest(
            year=year,
            month=month,
            participant_doctor_ids=[1, 2, 3],
        ),
        user_id=1,
    )
    # DiagnosticsSummary is a model, not a dict → use attribute access, not .get()
    pp(
        {
            "year": gen.year,
            "month": gen.month,
            "status": str(gen.status),
            "draft_version_id": gen.draft.version_id,
            "checkpoints_count": gen.draft.checkpoints_count,
            "diag_penalty_total": gen.diagnostics.summary.penalty_total,
        }
    )

    print("\n=== PUBLISH #1 ===")
    pub1 = svc.publish(
        year=year,
        month=month,
        force=False,  # MVP: no hard violations → succeeds without exceptions
        accepted_exceptions=None,  # Irrelevant when force=False and no violations
        note="First publication",
        user_id=1,
    )
    # audit may be Optional → guard with "or {}" before .keys()
    pp(
        {
            "published_version_id": pub1.published.version_id,
            "publications_count": pub1.published.publications_count,
            "can_undo": pub1.published.can_undo,
            "can_redo": pub1.published.can_redo,
            "audit_keys": sorted(list((pub1.published.audit or {}).keys())),
        }
    )

    print("\n=== PUBLISH #2 ===")
    pub2 = svc.publish(
        year=year,
        month=month,
        force=False,
        accepted_exceptions=None,
        note="Second publication",
        user_id=1,
    )
    pp(
        {
            "published_version_id": pub2.published.version_id,
            "publications_count": pub2.published.publications_count,
            "can_undo": pub2.published.can_undo,
            "can_redo": pub2.published.can_redo,
        }
    )

    print("\n=== REVERT published PREV ===")
    rev_prev = svc.revert(
        year=year,
        month=month,
        target="published",
        direction="prev",
        user_id=1,
    )
    assert isinstance(
        rev_prev, SchedulePublishedRevertRead
    ), "Expected SchedulePublishedRevertRead for published revert(prev)"
    pp(
        {
            "published_version_id": rev_prev.published.version_id,
            "publications_count": rev_prev.published.publications_count,
            "can_undo": rev_prev.published.can_undo,
            "can_redo": rev_prev.published.can_redo,
        }
    )

    print("\n=== REVERT published NEXT ===")
    rev_next = svc.revert(
        year=year,
        month=month,
        target="published",
        direction="next",
        user_id=1,
    )
    assert isinstance(
        rev_next, SchedulePublishedRevertRead
    ), "Expected SchedulePublishedRevertRead for published revert(next)"
    pp(
        {
            "published_version_id": rev_next.published.version_id,
            "publications_count": rev_next.published.publications_count,
            "can_undo": rev_next.published.can_undo,
            "can_redo": rev_next.published.can_redo,
        }
    )

    print("\nOK ✅  Smoke flow finished.")


if __name__ == "__main__":
    main()
