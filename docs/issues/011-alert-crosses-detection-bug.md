# Issue 011: "Crosses Above/Below" Alert Detection Bug

**Status:** Open
**Created:** 2026-02-04
**Priority:** High
**Affects:** Alert system

## Summary

"Crosses above" and "crosses below" alerts may fail to trigger in certain scenarios due to how `last_checked_value` is used for cross detection.

## Reported Incident

- **Date:** 2026-02-03
- **Alert:** Silver "crosses above" $78
- **Expected:** Notification when silver crossed above $78
- **Actual:** No notification received

## Root Cause Analysis

The cross detection logic in `AlertService._evaluate_condition()`:

```python
elif condition == "crosses_above":
    if last_value is None:
        return False, "No previous value for cross detection"
    triggered = last_value <= threshold and current_value > threshold
```

**Problems identified:**

### 1. No Initial Baseline
When an alert is created, `last_checked_value` is `None`. The first check will always return `False` with "No previous value for cross detection". This means:
- Alert created → first check → no trigger (no last_value)
- Second check → may or may not trigger depending on values

### 2. Incorrect Cross Detection Window
`last_checked_value` is updated on EVERY check (every 5 minutes), not stored as "price when alert was created" or "previous day's close". This means:

**Scenario:** Silver at $77.50 → alert checks → `last_value = $77.50`
Silver moves to $78.10 → alert checks → `$77.50 <= $78` AND `$78.10 > $78` → **TRIGGERS** ✓

**Problem scenario:** Silver at $78.10 when alert is created → first check → `last_value = $78.10`
Silver moves to $78.50 → alert checks → `$78.10 <= $78` is **FALSE** → **NEVER TRIGGERS** ✗

### 3. Gap/Jump Detection Failure
If price jumps significantly between checks (e.g., overnight gap), cross detection may fail:

**Scenario:** Silver at $77.50 at market close → overnight gap → opens at $79
- Last check (4 PM): `last_value = $77.50`
- First check (9:30 AM): current = $79, threshold = $78
- `$77.50 <= $78` AND `$79 > $78` → **TRIGGERS** ✓ (lucky!)

But if checks are 5 minutes apart and price was already above $78 at first check of day, it won't trigger.

## Proposed Fix

### Option A: Use Previous Close for Cross Detection
Instead of `last_checked_value`, compare against previous day's close:

```python
elif condition == "crosses_above":
    # Get previous close from quote data
    quote = await self.yahoo.get_quote(symbol)
    previous_close = quote.previous_close
    triggered = previous_close <= threshold and current_value > threshold
```

**Pros:** More intuitive for users ("notify me when it crosses $78 today")
**Cons:** Only detects daily crosses, not intraday

### Option B: Store Threshold-Relative State
Store whether we were above/below threshold, not the actual value:

```python
# In Alert model
was_above_threshold: bool = None

# In evaluation
elif condition == "crosses_above":
    currently_above = current_value > threshold
    if alert.was_above_threshold is None:
        # First check - establish baseline
        alert.was_above_threshold = currently_above
        return False, "Baseline established"

    triggered = not alert.was_above_threshold and currently_above
    alert.was_above_threshold = currently_above
```

**Pros:** Works for intraday and multi-day crosses
**Cons:** Requires schema migration

### Option C: Hybrid Approach (Recommended)
1. On alert creation, set `baseline_value` to current price
2. For cross detection, compare `baseline_value` to threshold, and current to threshold
3. Once triggered, update `baseline_value` to allow re-triggering if price dips and crosses again

```python
elif condition == "crosses_above":
    baseline = alert.baseline_value or alert.last_checked_value
    if baseline is None:
        # First check - establish baseline and check immediately
        alert.baseline_value = current_value
        triggered = current_value > threshold
        if triggered:
            alert.baseline_value = current_value  # Reset baseline after trigger
        return triggered, f"Baseline set to {current_value}"

    # Was baseline below threshold, and now above?
    triggered = baseline <= threshold and current_value > threshold
    if triggered:
        alert.baseline_value = current_value  # Reset for potential re-trigger
```

## Files Affected

- `backend/app/services/alert.py` - `_evaluate_condition()` method
- `backend/app/db/models/alert.py` - May need new field
- `backend/alembic/versions/` - Migration if adding field

## Testing Scenarios

After fix, verify these scenarios:

1. **Alert created when price is below threshold**
   - Create "crosses above $100" when price is $95
   - Price moves to $102 → should trigger

2. **Alert created when price is above threshold**
   - Create "crosses above $100" when price is $105
   - Price drops to $98, then rises to $102 → should trigger

3. **Intraday cross**
   - Create "crosses above $100" when price is $99
   - Price moves to $101 within same day → should trigger

4. **Overnight gap**
   - Price at $95 EOD
   - Opens at $105 next day
   - Should trigger (crossed through $100 overnight)

## Effort Estimate

- Analysis: 1 hour (done)
- Implementation: 2-3 hours
- Testing: 1-2 hours
- Migration (if needed): 30 min

**Total: ~4-6 hours**

## Related Issues

- Issue 022 (original user report, merged here)
