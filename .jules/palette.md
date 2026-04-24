## 2026-04-24 - Accessible Collapsible Components & Transient Feedback
**Learning:** Collapsible UI components must use `aria-expanded` and `aria-controls` to be accessible to screen readers. For transient state feedback (like "Copied!"), using a label transition with a 2000ms timeout is a non-disruptive way to provide confirmation without interrupting the user's flow with alerts.
**Action:** Always implement ARIA attributes on toggles and favor inline transient feedback over modal dialogs for micro-interactions.
