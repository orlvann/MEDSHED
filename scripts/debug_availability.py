# scripts/debug_availability_all_specialists.py
# English comments

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor
from backend.services.availability_service import _compute_available_days_for_doctor

YEAR = 2027
MONTH = 12
DAY = 24

with SessionLocal() as s:
    doctors = s.query(Doctor).filter_by(is_active=True).order_by(Doctor.id.asc()).all()

    print(f"Debug availability for YEAR={YEAR}, MONTH={MONTH}, DAY={DAY}")
    print("----------------------------------------------------------")

    spec_onsite_count = 0
    spec_oncall_count = 0
    res_onsite_count = 0
    res_oncall_count = 0

    for doc in doctors:
        available_onsite, available_oncall = _compute_available_days_for_doctor(
            s,
            year=YEAR,
            month=MONTH,
            doctor_id=doc.id,
        )

        is_onsite = DAY in available_onsite
        is_oncall = DAY in available_oncall

        # Count exactly like service.get_month_availability
        if doc.role == "specialist":
            if is_onsite:
                spec_onsite_count += 1
            if is_oncall:
                spec_oncall_count += 1
        else:
            if is_onsite:
                res_onsite_count += 1
            if is_oncall:
                res_oncall_count += 1

        print(
            f"Doctor {doc.id} {doc.first_name} {doc.last_name} "
            f"role={doc.role} | onsite_24={is_onsite} oncall_24={is_oncall}"
        )

    print("----------------------------------------------------------")
    print("SUMMARY COUNTS (should match API day=24):")
    print("specialists_onsite:", spec_onsite_count)
    print("specialists_oncall:", spec_oncall_count)
    print("residents_onsite:", res_onsite_count)
    print("residents_oncall:", res_oncall_count)
