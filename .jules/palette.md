## 2026-04-23 - [Transient button feedback for copy actions]
**Learning:** Replacing `window.alert` with transient inline feedback (e.g., '✅ Copied!') on the button itself significantly improves the user flow and provides a more modern, less disruptive UX.
**Action:** Use a 2000ms timeout for transient success feedback on interactive elements like copy buttons.

## 2026-04-23 - [Accessible Collapsible Panels]
**Learning:** Collapsible UI components must use `aria-expanded` on the toggle button and `aria-controls` linked to the content container's unique `id` to ensure accessibility for screen readers.
**Action:** Always implement `aria-expanded`, `aria-controls`, and `role="region"` for panels that can be toggled open/closed.
