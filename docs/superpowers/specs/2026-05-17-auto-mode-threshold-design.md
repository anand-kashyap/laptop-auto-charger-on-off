# Auto Mode Threshold Semantics Design

## Summary

`auto` mode must ignore `START_TIME` and `END_TIME` entirely and control charger state only from battery thresholds. `schedule` remains legacy behavior for time-window testing. `always_on` stays unchanged.

## Problem

Current mode logic is split inline inside the monitor loop. That makes `auto` behavior easy to misread and easy to regress when schedule logic changes. The desired behavior is simple:

- `auto` uses only battery thresholds
- `schedule` uses schedule window plus thresholds
- `always_on` always enables charging

The code should make that separation obvious in one place.

## Goals

1. Make `auto` mode pure threshold control.
2. Keep `schedule` behavior intact for legacy/testing use.
3. Preserve `always_on` behavior.
4. Keep plug control library usage unchanged.
5. Keep Windows helper/restart behavior unchanged.

## Non-goals

1. No changes to `plugp100` connection or control calls.
2. No changes to mode-switch helper semantics.
3. No new modes.
4. No changes to battery reading or notification behavior.

## Proposed Design

### Decision Function

Extract one pure decision function for charger intent. The caller computes schedule-window state once and passes it in, so the helper stays free of direct time lookup. The function should take mode, battery percent, current plug state, and schedule-window state, then return whether charger should be on.

Recommended shape:

```python
def should_charge(mode, percent, plug_on, is_schedule_window):
    ...
```

Behavior:

- `always_on`: return `True`
- `auto`: ignore `is_schedule_window`; use battery thresholds only
- `schedule`: use `is_schedule_window` to decide whether to apply threshold control

### Mode Rules

`auto`:

- If `percent > HIGH_THRESHOLD`, return `False`
- If `percent < LOW_THRESHOLD`, return `True`
- If `LOW_THRESHOLD <= percent <= HIGH_THRESHOLD`, return current `plug_on`
- `START_TIME` and `END_TIME` are irrelevant in this mode

`schedule`:

- If outside schedule window, return `True`
- If inside schedule window, apply the same threshold rules as `auto`

`always_on`:

- Return `True` unconditionally

### Schedule Window Computation

`is_schedule_window` is computed in caller code only when `schedule` mode needs it. `auto` must not consult schedule-window logic at all, even as an intermediate branch.

### Integration Point

The monitor loop keeps all current responsibilities except the inline mode branch:

- battery read
- Tapo connect/reconnect
- notification handling
- plug state read
- decision function call
- turn_on / turn_off if needed

The loop should not contain mode-specific charging logic after refactor.

## Error Handling

Keep existing error handling unchanged:

- battery unavailable -> log and sleep
- plug connect failure -> log, notify if needed, sleep, retry
- plug update failure -> log, notify if needed, sleep, retry

Decision function should not raise for normal mode inputs. If mode is invalid, it should fail fast in a way that surfaces during startup or test execution.

## Acceptance Criteria

1. `auto` never depends on `START_TIME` or `END_TIME` for charger decisions.
2. `schedule` behavior matches current legacy behavior.
3. `always_on` still forces charger on.
4. Refactor is isolated to charging decision logic.