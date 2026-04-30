## 2025-05-14 - [A11y] Global Focus and Interaction States
**Learning:** In utility-heavy or minimal-framework apps, base HTML elements often lack consistent focus indicators. Applying global `:focus-visible` styles ensures that all interactive elements are keyboard-accessible without needing to remember to add classes to every new component.
**Action:** Always check for `:focus-visible` support and implement a high-contrast focus ring as a baseline for any project.

## 2025-05-14 - [UX] Feedback for Async Actions
**Learning:** Users can feel uncertain when a "Save" action has no visual response, often leading to double-clicks or frustration. Adding a simple `saving` state to buttons provides immediate confirmation that the system is processing.
**Action:** Implement loading states for all primary action buttons that trigger network requests.

## 2026-04-12 - [UX] Completeness in Debug and Audit Logs
**Learning:** Transition events that disable a logging feature must themselves be logged before the feature is deactivated. If the state check happens before recording the 'Disabled' event, the audit trail becomes incomplete and confusing to users.
**Action:** Always allow "Disable" transition events to bypass state-based logging filters.

## 2026-04-13 - [UX/A11y] Non-intrusive Feedback and Accessible Disclosure
**Learning:** Modal alerts (window.alert) for routine success confirmations like "Copied" are disruptive to user flow. Transient inline feedback (e.g., "✅ Copied!") provides sufficient confirmation without requiring user interaction to dismiss. Additionally, collapsible panels require explicit ARIA relationships (aria-expanded/aria-controls) and landmark roles (role="region") to be discoverable and understandable by screen reader users.
**Action:** Favor transient state-based feedback over modal dialogs for success states. Ensure all disclosure components implement standard ARIA patterns for accessibility.
