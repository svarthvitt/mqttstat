## 2025-05-14 - [A11y] Global Focus and Interaction States
**Learning:** In utility-heavy or minimal-framework apps, base HTML elements often lack consistent focus indicators. Applying global `:focus-visible` styles ensures that all interactive elements are keyboard-accessible without needing to remember to add classes to every new component.
**Action:** Always check for `:focus-visible` support and implement a high-contrast focus ring as a baseline for any project.

## 2025-05-14 - [UX] Feedback for Async Actions
**Learning:** Users can feel uncertain when a "Save" action has no visual response, often leading to double-clicks or frustration. Adding a simple `saving` state to buttons provides immediate confirmation that the system is processing.
**Action:** Implement loading states for all primary action buttons that trigger network requests.

## 2026-04-12 - [UX] Completeness in Debug and Audit Logs
**Learning:** Transition events that disable a logging feature must themselves be logged before the feature is deactivated. If the state check happens before recording the 'Disabled' event, the audit trail becomes incomplete and confusing to users.
**Action:** Always allow "Disable" transition events to bypass state-based logging filters.

## 2025-05-14 - Non-disruptive feedback for clipboard actions
**Learning:** Replacing `window.alert` with transient inline button feedback (e.g., "✅ Copied!") significantly improves user flow by avoiding modal interruptions.
**Action:** Use a 2000ms timeout with a React state and `useEffect` cleanup for consistent, non-disruptive interaction feedback across the app.
