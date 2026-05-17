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

Extract one pure decision function for charger intent. The function should take mode, battery percent, and current plug state, then return whether charger should be on.

Recommended shape:

```python
def should_charge(mode, percent, plug_on, is_night_window):
    ...
```

Behavior:

- `always_on`: return `True`
- `auto`: ignore `is_night_window`; use battery thresholds only
- `schedule`: use `is_night_window` to decide whether to apply threshold control

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

## Testing

Add focused tests for the decision function. Suggested coverage:

1. `always_on` returns `True` for any battery percent and plug state.
2. `auto` turns OFF above `HIGH_THRESHOLD`.
3. `auto` turns ON below `LOW_THRESHOLD`.
4. `auto` holds current plug state in deadband.
5. `auto` ignores schedule window input completely.
6. `schedule` turns ON outside window.
7. `schedule` applies thresholds inside window.
8. `schedule` holds current plug state in deadband inside window.

Use a small matrix-style unit test table rather than end-to-end hardware tests.

## Acceptance Criteria

1. `auto` never depends on `START_TIME` or `END_TIME` for charger decisions.
2. `schedule` behavior matches current legacy behavior.
3. `always_on` still forces charger on.
4. Refactor is isolated to charging decision logic.
5. Tests cover all mode/threshold combinations above.

## Open Questions

1. Whether to keep the helper signature as `should_charge(mode, percent, plug_on, is_night_window)` or compute schedule window only in the caller is an implementation detail. The behavior stays the same either way.
2. Whether to rename `is_night_window` to `is_schedule_window` is optional cleanup only.