# Issue 010: Mobile Responsive Design Fixes

**Status:** Open
**Created:** 2026-02-04
**Priority:** Medium
**Affects:** Equity page (mobile), various components

## Summary

Several UI elements overflow or don't display correctly on mobile viewports, particularly on the equity detail page.

## Issues Identified

### 1. AI Analysis Button Overflow
- On mobile, the AI analysis button/panel extends outside the viewport
- Tab bar buttons may overflow horizontally
- AI panel (500px height) takes too much screen space

### 2. Tab Navigation Overflow
- Equity page tabs (Overview, AI Analysis, etc.) can overflow
- No horizontal scroll or wrapping on small screens

### 3. Chart Controls
- Period selector buttons may wrap awkwardly
- Volume toggle and other controls crowd together

## Proposed Fixes

### 1. AI Analysis Panel
```tsx
// Current: fixed height
className="h-[500px]"

// Fix: responsive height with max
className="h-[60vh] max-h-[500px] min-h-[300px]"
```

### 2. Tab Navigation
```tsx
// Current: flex row, no scroll
<div className="flex gap-2">

// Fix: horizontal scroll on mobile
<div className="flex gap-2 overflow-x-auto pb-2 -mb-2 scrollbar-hide">
```

### 3. Chart Controls
```tsx
// Current: all buttons inline
<div className="flex items-center gap-2">

// Fix: wrap on mobile
<div className="flex flex-wrap items-center gap-2">
```

### 4. Button Text
```tsx
// Current: always show text
<span>AI Analysis</span>

// Fix: hide text on mobile
<span className="hidden sm:inline">AI Analysis</span>
```

## Files Affected

- `frontend/src/app/equity/[symbol]/page.tsx` - Tab layout, AI panel
- `frontend/src/components/ai/AIAnalysisPanel.tsx` - Panel sizing
- `frontend/src/components/charts/ChartControls.tsx` - Control layout
- `frontend/src/components/equity/QuoteHeader.tsx` - Header layout

## Testing Approach

Test on these viewport widths:
- 320px (iPhone SE)
- 375px (iPhone 12/13)
- 390px (iPhone 14)
- 768px (iPad portrait)

## Effort Estimate

- Audit all components for mobile issues: 1-2 hours
- Apply responsive fixes: 2-3 hours
- Testing across viewports: 1-2 hours
- Refinements: 1 hour

**Total: ~5-8 hours (1 day)**

## Future Considerations

- Consider mobile-first redesign for equity page
- Tab navigation could become bottom sheet on mobile
- Chart could be full-width on mobile
