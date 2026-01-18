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

So far we added **rest rules** as a soft objective:
- The solver tries to avoid giving the same doctor duties on **two consecutive days**.

We test these soft rules:

1. **onsite -> onsite on consecutive days** should be avoided (highest penalty)
2. **oncall -> oncall on consecutive days** should be avoided (lower penalty)
3. **cross-shift between days** should be avoided:
   - onsite day d -> oncall day d+1
   - oncall day d -> onsite day d+1
   - cross-shift penalty is **higher for specialists** than for residents

4. **Weekend exception (Sat -> Sun only, cross-shift only)**
   - If a doctor has `allow_weekend_consecutive_onsite_oncall=True`,
     then cross-shift Sat->Sun for that doctor is **NOT penalized**.
   - This exception applies only to cross-shift.

Pewnie — dopisałem gotową sekcję do wklejenia, z Twoimi markerami (`unit`, `integration`) i praktycznymi komendami.

````md
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

#### 7) Run tests by marker (unit vs integration)

We use pytest markers to group tests:

* `unit`: fast tests that do NOT run the OR-Tools solver
* `integration`: tests that DO run the OR-Tools solver (still no DB / no API)

Run only unit tests:

```bash
pytest -m unit -vv
```

Run only integration tests:

```bash
pytest -m integration -vv
```

Run everything except integration tests:

```bash
pytest -m "not integration" -vv
```

Note:
Markers must be registered in `pytest.ini` under `[pytest] markers = ...`
(otherwise pytest will show warnings about unknown markers).

```
```
