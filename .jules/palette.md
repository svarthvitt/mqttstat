## 2025-05-15 - [Non-disruptive feedback for clipboard actions]
**Learning:** Replacing `window.alert` with transient inline feedback (e.g., "✅ Copied!") on the triggering button significantly improves user flow by avoiding disruptive modal dialogs.
**Action:** Favor transient inline state changes for non-critical confirmations like "Copied" or "Saved" using a 2000ms timeout and `useEffect` cleanup.

## 2025-05-15 - [Accessible collapsible regions]
**Learning:** For accessible collapsible panels, always pair `aria-expanded` and `aria-controls` on the trigger with a matching `id` and `role="region"` on the content container.
**Action:** Standardize collapsible components to use this ARIA pattern to ensure screen readers correctly announce the state and relationship.
