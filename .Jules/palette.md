## 2025-05-14 - [A11y] Global Focus and Interaction States
**Learning:** In utility-heavy or minimal-framework apps, base HTML elements often lack consistent focus indicators. Applying global `:focus-visible` styles ensures that all interactive elements are keyboard-accessible without needing to remember to add classes to every new component.
**Action:** Always check for `:focus-visible` support and implement a high-contrast focus ring as a baseline for any project.

## 2025-05-14 - [UX] Feedback for Async Actions
**Learning:** Users can feel uncertain when a "Save" action has no visual response, often leading to double-clicks or frustration. Adding a simple `saving` state to buttons provides immediate confirmation that the system is processing.
**Action:** Implement loading states for all primary action buttons that trigger network requests.
