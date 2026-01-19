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

5. **Weekday patterns (ETAP 4A)**

* Lower-priority tie-breaker based on weekday preferences (0=Mon .. 6=Sun).
* The solver adds:

  * a small **bonus** for assigning a doctor on their `preferred_*_weekdays`
  * a small **penalty** for assigning a doctor on their `avoid_*_weekdays`
* This objective is defensive:

  * if the slot variable does not exist (forbidden / filtered), the term is skipped (no crash)
* This is tested on a **single day** scenario, so rest rules do not matter:

  * `tests/solver/test_objective_weekday_patterns.py`

    * preferred weekday breaks tie
    * avoid weekday breaks tie

6. **Preferred partners**

* Lower-priority tie-breaker based on `preferred_partners: list[int]`.
* The solver adds a small **bonus** when two preferred partners work on the **same day**
  (any combination of shifts: onsite/oncall).
* Defensive behavior:

  * if a slot variable does not exist (forbidden / filtered), the term is skipped (no crash)
  * pairs are counted only once (`doc_id < partner_id`)
* Tests:

  * `tests/solver/test_objective_preferred_partners.py`

    * partner bonus pushes partners to work on the same days
    * with partner >= without partner (together count)

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
