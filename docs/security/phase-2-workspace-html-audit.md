# Phase 2 — workspace HTML sink audit

**Scope:** `app/server/web/workspace.js` on `feature/security-hardening-2026-10`.

The source scan found 28 `innerHTML` assignment occurrences. Several are deliberate clears or static placeholders rather than untrusted HTML construction. The review below records the rendering paths and their controls.

| Sink / function | Data entering HTML | Review result |
|---|---|---|
| `loadDepartments` — invite department options | Department ID and name | Both pass through `esc()`; ID is in a quoted attribute. |
| Department action cell | No dynamic content; `innerHTML = ""` | Clear-only operation; buttons are created with DOM APIs and `textContent`. |
| Template-field action cell | No dynamic content; `innerHTML = ""` | Clear-only operation; buttons are created with DOM APIs and `textContent`. |
| `renderChartTemplate` host clear / empty state | Static markup only | No API-controlled markup in these two assignments. Dynamic section headings and labels use `textContent`. |
| Choice-field options | Choice text and option value | Both text and value pass through `esc()`; selected state is a boolean condition. |
| Import report | Counts, row number, patient name, error text | All interpolated values are escaped. |
| `loadDirectory` department options | Department ID and name | Both escaped. |
| Patient chart header | Patient name, number, sex, age, department, blood pressure, history | All API-derived text values, including age, are escaped. |
| Chart department chips | Department names | Escaped. |
| Appointment provider options | Provider value and label | Escaped in both contexts. |
| Appointment summary | Appointment count, patient name, formatted date | Count and name escaped; date formatter returns a formatted date or escaped invalid input. |
| Staff department options | Department ID and name | Both escaped. |
| Permission-filtered department picker | Department ID and name | ID and name escaped; checked state is a boolean condition. |
| Provider datalist | Provider values | Escaped. |
| Temporary-access patient picker | Patient ID, name, patient number | All interpolated values escaped. |
| Temporary-access selected chips | Label and data ID | Both escaped; action buttons are wired after rendering. |
| Table header/body clears | No dynamic content | Clear-only assignments. |
| Empty table state | Column count | Count escaped; remaining markup is static. |
| Table header construction | Column labels | Labels escaped. Current labels are code-defined, but the sink is safe if that changes. |
| Table row construction | API values and formatted date values | Ordinary values pass through `esc()`; dates use `fmtDT()`, which escapes invalid input. |
| Chart-list clear / empty state | No dynamic content | Clear-only or static placeholder. |
| Chart-list item rendering | Clinical values, notes, timestamps, statuses | Text values use `esc()`; CSS classes are selected from fixed comparisons, not interpolated raw values. |
| Notifications list | Notification ID, title, body, timestamp, read state | ID and text values escaped; class and read-state labels derive from a boolean. |
| Notification error state | Error message | Escaped. |
| Settings navigation | Section ID and label | Values are code-defined and also escaped before insertion. |

## Shared escaper

The shared `esc()` function escapes ampersands first, then angle brackets and both quote characters. This covers ordinary text nodes and quoted attribute values. Escaping is context-dependent: it is not a substitute for URL validation, JavaScript-context encoding, or safe DOM APIs.

## Follow-up and limits

- The source-contract tests verify that quote escaping and selected attribute sinks remain guarded. They do **not** simulate a browser DOM; add Playwright/browser-level payload tests when the project has a maintained browser-test setup.
- Prefer `textContent`, DOM node creation, and explicit property assignment for new dynamic UI. Avoid adding new `innerHTML` sinks.
- Session storage remains a separate review item. This audit does not claim that storing bearer tokens in `localStorage` is XSS-safe.
