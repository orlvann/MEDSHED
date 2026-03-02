````md
# Tests

This folder contains automated tests for the project.

## Solver tests

Location: `tests/solver/`

These tests check the **core scheduling solver** (the OR-Tools CP-SAT part).  
The solver takes a prepared `HardModel` (input data for one month) and tries to produce a valid schedule.

### What the solver should do (current stage)

The solver creates assignments for each **active day**:

- **Onsite shift** (one doctor) if this shift is required (not ignored)
- **Oncall shift** (one doctor) if this shift is required (not ignored)

An "active day" means:

- it is inside the month,
- it is NOT in `ignore_days`,
- and it is not a day where **both** shifts are ignored via `ignore_slots`.

The solver uses two kinds of rules:

#### A) Hard constraints (must be satisfied, otherwise no schedule is possible)

We test that the solver enforces all hard rules:

1. **Coverage rule (per active day, per required shift)**

   - If `(day, ShiftType.onsite)` is NOT in `ignore_slots`, the solver must assign exactly **1 doctor** to onsite.
   - If `(day, ShiftType.oncall)` is NOT in `ignore_slots`, the solver must assign exactly **1 doctor** to oncall.

2. **Specialist-per-day rule**

   - For each active day, among the **required shifts** (onsite and/or oncall),  
     there must be **at least one specialist** assigned.
   - If both shifts are ignored for a day, the rule is skipped for that day.

3. **No double shift on the same day**

   - The same doctor cannot be assigned to **onsite and oncall on the same day**.

4. **Allowed slots rule (availability / ignore rules already applied)**

   - The solver is allowed to assign doctors only in slots that exist in `allowed_slots`.
   - If a slot is not allowed (unavailable / ignored / removed earlier),  
     the solver must not "invent" an assignment there.

If hard rules cannot be satisfied, the solver returns:

- `EMPTY`: there is nothing to schedule because `allowed_slots` is an empty dict (`{}`), so the solver has no variables to build.
- `INFEASIBLE`: the CP-SAT model has no valid solution  
  (for example, a required shift has zero candidates, or no specialist can cover a day).

Important: availability and ignore rules are applied **before** the solver.  
`constraint_builder.build_hard_model(...)` builds:

- `active_days` (days we actually schedule),
- `allowed_slots` (who is allowed to work each `(day, shift)`).  

The solver (`engine.build_and_solve`) does not re-check unavailability lists.  
It only uses `allowed_slots`, `active_days`, and `ignore_slots`.

#### B) Soft constraints (preferences, "try to avoid", but do not block feasibility)

Soft constraints do NOT make the solver fail.  
They only tell the solver which valid solution is "better".

So far we added these soft objectives:

1. **Rest rules**

- The solver tries to avoid giving the same doctor duties on **two consecutive days**.

We test these rest rules:

- **onsite -> onsite on consecutive days** should be avoided (highest penalty)
- **oncall -> oncall on consecutive days** should be avoided (lower penalty)
- **cross-shift between days** should be avoided:
  - onsite day d -> oncall day d+1
  - oncall day d -> onsite day d+1
  - cross-shift penalty is **higher for specialists** than for residents

Weekend exception (Sat -> Sun only, cross-shift only):

- If a doctor has `allow_weekend_consecutive_onsite_oncall=True`,  
  then cross-shift Sat->Sun for that doctor is **NOT penalized**.
- This exception applies only to cross-shift.

2. **Preferred concrete days**

- The solver tries to satisfy:
  - `preferred_onsite_days`
  - `preferred_oncall_days`
- If a preferred slot is impossible (missing `x` variable / forbidden slot),  
  we skip the penalty (MVP rule).
- Missing a preferred day is weighted by doctor importance:  
  a doctor who is both **head** and **specialist** has a higher miss penalty  
  than a plain specialist.

3. **Totals**

The solver tries to match per-doctor totals using:

- monthly totals:
  - `max_*_total`
  - `target_*_total`
- weekend totals:
  - `max_*_weekends`
  - `target_*_weekends`

Important:

- Max and target penalties are quadratic (escalating): `deviation^2` / `excess^2`.  
  This encourages spreading unavoidable violations across doctors instead of concentrating them.
- Totals objective is defensive:
  - if a day/slot has no `x` variables (e.g. ignored day), it must not crash
  - if `participant_doctor_ids` is empty, it returns a valid `0` IntVar

4. **Role-group fairness**

- If multiple feasible schedules exist and other objectives do not differentiate them,  
  the solver prefers a more even distribution of shifts **inside each role group**  
  (specialists compared with specialists, residents compared with residents).
- This is tested on **non-consecutive weekdays** to avoid rest-rule influence.

5. **Weekday patterns**

- Lower-priority tie-breaker based on weekday preferences (0=Mon .. 6=Sun).
- The solver adds:
  - a small **bonus** for assigning a doctor on their `preferred_*_weekdays`
  - a small **penalty** for assigning a doctor on their `avoid_*_weekdays`
- This objective is defensive:
  - if the slot variable does not exist (forbidden / filtered), the term is skipped (no crash)
- This is tested on a **single day** scenario, so rest rules do not matter:
  - `tests/solver/test_objective_weekday_patterns.py`
    - preferred weekday breaks tie
    - avoid weekday breaks tie

6. **Preferred partners**

- Lower-priority tie-breaker based on `preferred_partners: list[int]`.
- The solver adds a small **bonus** when two preferred partners work on the **same day**  
  (any combination of shifts: onsite/oncall).
- Defensive behavior:
  - if a slot variable does not exist (forbidden / filtered), the term is skipped (no crash)
  - pairs are counted only once (`doc_id < partner_id`)
- Tests:
  - `tests/solver/test_objective_preferred_partners.py`
    - partner bonus pushes partners to work on the same days
    - with partner >= without partner (together count)

7. **Avoid Friday if weekend off**

- Lower-priority tie-breaker.
- The solver adds a small **penalty** when a doctor works on **Friday**  
  and has the whole following weekend **fully off**.
- "Following weekend" means the immediate **Saturday and Sunday** right after that Friday:  
  `sat = fri + 1`, `sun = fri + 2` (only if both days exist in the model and are really Sat/Sun).
- "Weekend off" means the doctor has **no duty** on Saturday and **no duty** on Sunday  
  (neither onsite nor oncall).
- Defensive behavior:
  - if the weekend days are missing (e.g. last Friday in model), the rule is skipped (no crash).
- Tests:
  - `tests/solver/test_objective_avoid_friday_free_weekend.py`
    - prefers assigning Friday to a doctor who also works the weekend (to avoid the penalty)
    - is soft (still solves when Friday has only one candidate)
    - skips when weekend days are not present in the model

### Seeding (warm-start hints)

Before solving, the engine can provide **hints** (warm-start suggestions) to CP-SAT.
Hints are **NOT constraints**: the solver may ignore them if they conflict with better solutions
or with other objectives. We test seeding logic directly for determinism.

1. **Head commitments (must-have head preferred slots)**

Heads can express "must-have" preferred days (commitments). These are validated **before**
building/solving the CP model.

Rules:

- If a head preferred slot is ignored -> `INFEASIBLE` + issue
- If a head preferred slot is not allowed -> `INFEASIBLE` + issue
- If multiple heads prefer the same slot -> `INFEASIBLE` + issue
- If the same head prefers onsite and oncall on the same day -> `INFEASIBLE` + issue

Tests:

- `tests/solver/test_seeding_head_commitments.py`
  - conflict between two heads
  - commitment into ignored slot
  - commitment not allowed by `allowed_slots`
  - head requests both shifts on the same day

2. **TOP K hardest slots by difficulty (hinting)**

This is pure warm-start logic: it chooses up to **K = 10** slots that are hardest to cover,
and adds exactly one `1` hint per seeded slot (the deterministic smallest doctor_id per slot).

Rules (confirmed):

- Build candidate slots = all "in play" slots:
  - day in `model.active_days`
  - slot not ignored (not in `model.ignore_slots`)
  - slot key exists in `model.allowed_slots`
  - excluding slots already seeded by head commitments
- `difficulty = len(model.allowed_slots[(day, shift_type)])`
- Sort by `(difficulty asc, day asc, shift_type asc)`
- Seed TOP K slots, where `K = min(10, number_of_slots)`

Tests:

- `tests/solver/test_seeding_top_k_difficulty.py`
  - creates 12 slots with difficulties 1..12 and verifies only 10 are seeded

3. **General seeding integration (hint map content)**

We also keep focused tests checking the hint map produced by `seeding.generate_initial_hints(...)`,
without going through `engine.build_and_solve(...)`.

Tests:

- `tests/solver/test_seeding_hints.py`
  - seeding includes the head commitment hint
  - seeding selects TOP K slots by difficulty as expected

### Post-solve infeasible explanation (CP-SAT stage)

When the CP-SAT solver returns `INFEASIBLE`, the engine tries to attach **user-friendly issues**
explaining *why* it failed at the CP stage.

Rules:

- Prefer **day-level reasons** derived deterministically from `HardModel`:
  - missing candidates for a required slot (`no_onsite_candidate`, `no_oncall_candidate`)
  - missing specialist **only when BOTH shifts are required** (`no_specialist`)
  - forced double shift on the same day (`forced_double_shift_same_day`)
- If no day-level reason can be derived, return a global fallback issue:
  - `day=0`, `code=cp_infeasible`

Tests:

- `tests/solver/test_engine_infeasible_issues.py`
  - missing onsite candidates -> `no_onsite_candidate`
  - missing specialist -> `no_specialist`
  - forced double shift -> `forced_double_shift_same_day`
  - fallback -> `cp_infeasible` (day=0)

### Engine non-OK statuses (no issues attached)

Not every non-OK status should produce issues:

- `EMPTY` means there are no variables to build (`allowed_slots == {}`), so there is no CP-SAT infeasibility to explain.
- `NOT_SOLVED` means CP-SAT did not return a definite answer (e.g. `UNKNOWN`), so we do not guess issues.

Tests:

- `tests/solver/test_engine_non_ok_statuses.py`
  - `EMPTY` returns no issues
  - `NOT_SOLVED` returns no issues

### Shared issue codes (single source of truth)

All issue codes and their default human-readable messages live in:

- `backend/core/issues.py`

This module is the **single source of truth** for:

- issue code constants (for feasibility, availability warnings, head commitments, CP-SAT infeasible),
- default messages (`FEASIBILITY_ISSUE_MESSAGES`),
- helper functions that classify issues (counts-based and identity-based),
- availability risk helper that returns `RiskLevel` + machine-readable reasons for UI.

Rule:
- Do NOT re-implement issue classification in other modules.
  Other code should call helpers from `backend/core/issues.py` instead.

### Feasibility pre-check (ignore_slots + identity-based checks)

Before CP-SAT is built, we run a fast feasibility pre-check (`backend/core/feasibility.analyze_problem`).
These tests guarantee correct behavior around ignored slots and identity-aware edge cases.

Key guarantees:

- If a slot is ignored, it is NOT required, so we must NOT emit:
  - `no_onsite_candidate` for an ignored onsite slot
  - `no_oncall_candidate` for an ignored oncall slot
- `forced_double_shift_same_day` is emitted only when BOTH shifts are required and the only onsite candidate
  and the only oncall candidate is the same single doctor (identity-based detection).
- Policy: `no_specialist` is emitted only when BOTH shifts are required.

Tests:

- `tests/solver/test_feasibility_ignore_slots.py`
  - ignored onsite does not emit `no_onsite_candidate`
  - single-candidate-for-both not emitted when one shift is ignored
  - only-oncall-required + no oncall candidates emits `no_oncall_candidate`
- `tests/solver/test_feasibility_forced_double_shift.py`
  - forced double shift is detected when the same single doctor is the only candidate for both shifts
  - not emitted when the only candidates are different doctors
- `tests/solver/test_feasibility_no_specialist_only_when_both_required.py`
  - `no_specialist` is not emitted when only one shift is required
  - `no_specialist` is emitted when both shifts are required and union has no specialist

### Issue codes + availability risk helpers (counts-based)

We also test shared helpers in `backend/core/issues.py` that are used by availability UI and other diagnostics.

Rules:

- If a day is totally empty (`total_onsite == 0` AND `total_oncall == 0`), return ONLY:
  - `no_candidates_for_day`
  (and do NOT duplicate it with `no_onsite_candidate` / `no_oncall_candidate`)
- For non-empty cases, return the correct minimal set of issue codes.
- Risk classifier:
  - `RiskLevel.ok` returns `issues=[]`
  - empty day becomes `RiskLevel.critical` and includes `no_candidates_for_day`

Tests:

- `tests/solver/test_issues_counts_and_risk.py`
  - empty day -> only `no_candidates_for_day`
  - only onsite missing -> only `no_onsite_candidate`
  - ok risk -> no issues
  - empty day risk -> critical + `no_candidates_for_day`

### How to run the tests (simple commands)

You run tests using `pytest` (a Python test runner).

#### 1) Run ALL tests in the repository

```bash
pytest
````

#### 2) Run ALL tests (verbose output)

```bash
pytest -vv
```

Explanation: `-vv` prints every test name and its result.

#### 3) Stop on the first failure (useful for debugging)

```bash
pytest -x -vv
```

Explanation:

* `-x` stops after the first failing test (faster feedback)
* `-vv` shows each test name

#### 4) Show print() output (only when you really need it)

```bash
pytest -x -vv -s
```

Explanation:

* `-s` disables output capture, so `print()` is visible

#### 5) Run only solver tests

```bash
pytest tests/solver -vv
```

#### 6) Run a single test file

Hard constraints:

```bash
pytest tests/solver/test_engine_hard.py -vv
```

Seeding: head commitments validation:

```bash
pytest tests/solver/test_seeding_head_commitments.py -vv
```

Seeding: TOP K difficulty:

```bash
pytest tests/solver/test_seeding_top_k_difficulty.py -vv
```

Seeding: general hints:

```bash
pytest tests/solver/test_seeding_hints.py -vv
```

Post-solve infeasible explanation:

```bash
pytest tests/solver/test_engine_infeasible_issues.py -vv
```

Engine non-OK statuses:

```bash
pytest tests/solver/test_engine_non_ok_statuses.py -vv
```

Feasibility pre-check (ignore_slots rules):

```bash
pytest tests/solver/test_feasibility_ignore_slots.py -vv
```

Feasibility pre-check (forced double shift identity detection):

```bash
pytest tests/solver/test_feasibility_forced_double_shift.py -vv
```

Feasibility pre-check (NO_SPECIALIST only when both required):

```bash
pytest tests/solver/test_feasibility_no_specialist_only_when_both_required.py -vv
```

Shared issue codes + availability risk helpers:

```bash
pytest tests/solver/test_issues_counts_and_risk.py -vv
```

Soft objective (rest rules):

```bash
pytest tests/solver/test_objective_rest.py -vv
```

Soft objective (preferred days):

```bash
pytest tests/solver/test_objective_preferred_days.py -vv
```

Soft objective (totals):

```bash
pytest tests/solver/test_objective_totals.py -vv
```

Soft objective (fairness):

```bash
pytest tests/solver/test_objective_fairness.py -vv
```

Soft objective (weekday patterns):

```bash
pytest tests/solver/test_objective_weekday_patterns.py -vv
```

Soft objective (preferred partners):

```bash
pytest tests/solver/test_objective_preferred_partners.py -vv
```

Soft objective (avoid Friday if weekend off):

```bash
pytest tests/solver/test_objective_avoid_friday_free_weekend.py -vv
```

#### 7) Run tests by marker (unit vs solver)

We use pytest markers to group tests:

* `unit`: fast tests that do NOT run the OR-Tools solver (pure logic checks)
* `solver`: tests that DO run the OR-Tools solver (no DB / no API)

Run only unit tests:

```bash
pytest -m unit -vv
```

Run only solver tests:

```bash
pytest -m solver -vv
```

Run everything except solver tests:

```bash
pytest -m "not solver" -vv
```

Note:
Markers must be registered in `pytest.ini` under `[pytest] markers = ...`
(otherwise pytest will show warnings about unknown markers).

```
```