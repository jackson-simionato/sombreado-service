# Ida Before Volta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return Direction Choices in `ida`, `volta`, then unclassified order while preserving sequence within each group.

**Architecture:** Keep the SQL query and public schema unchanged. Sort mapped `DirectionChoice` values in `RouteReadService.load_direction_choices` with an explicit semantic rank and `sequence` tie-breaker.

**Tech Stack:** Python 3.13, SQLAlchemy, pytest, Ruff

## Global Constraints

- Apply only to `GET /v1/routes/{routeId}/directions`.
- Preserve the existing response shape and Direction Choice eligibility.
- Preserve ascending `sequence` within each direction-kind group.

---

### Task 1: Semantic Direction Choice Ordering

**Files:**
- Modify: `tests/test_route_read_service.py`
- Modify: `app/services/routes.py`
- Modify: `docs/plans/route-direction-kind-browser-contract.md`

**Interfaces:**
- Consumes: `RouteReadService.load_direction_choices(*, route_version_id: UUID) -> list[DirectionChoice]`
- Produces: the same method and return type with deterministic semantic ordering

- [ ] **Step 1: Write the failing test**

Extend the direction-choice mapping test with mixed `volta`, `ida`, and null rows, including multiple sequences in one group, then assert the returned `(direction_kind, sequence)` values equal:

```python
[("ida", 1), ("ida", 3), ("volta", 2), (None, 4)]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run python -m pytest -q tests/test_route_read_service.py::test_load_direction_choices_maps_rows_for_current_version`

Expected: FAIL because current behavior follows source row order.

- [ ] **Step 3: Implement the minimal semantic sort**

Map rows as today, then sort choices with an explicit rank:

```python
direction_kind_order = {"ida": 0, "volta": 1, None: 2}
directions.sort(key=lambda direction: (direction_kind_order[direction.direction_kind], direction.sequence))
```

- [ ] **Step 4: Update the contract note**

Replace the obsolete no-reordering statement with the new `ida`, `volta`, unclassified ordering rule and sequence tie-breaker.

- [ ] **Step 5: Verify GREEN and repository completion gates**

Run:

```bash
uv run python -m pytest -q tests/test_route_read_service.py::test_load_direction_choices_maps_rows_for_current_version
uv run ruff format .
uv run ruff check .
uv run python -m pytest -q
```

Expected: all commands exit successfully.
