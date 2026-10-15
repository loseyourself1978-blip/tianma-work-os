# R2 modal interaction contract

2026-10-09 follow-up to the existing project-first R2 UI work.

The previous modal shell placed its Close button below a full-width language
selector. A control existing in the DOM did not make its placement usable.
The shared shell now provides a persistent top-left × control, a separate
language selector, a scrollable body, and a localized accessible name and title.
This control closes a TWOS dialog, not a Safari tab or macOS window.

Required checks:

- The close target is visible, unobscured, at least 40 × 40 CSS pixels, and in
  the top-left corner at desktop and narrow widths.
- It stays reachable without scrolling the body back to the top.
- Normal close clicks dismiss the dialog and return keyboard focus to its
  initiating action. Locale re-rendering must not lose that logical target.
- Browser cancel behavior preserves unsaved local drafts and source selection.
  Native Escape must also be checked in packaged Safari GUI evidence.
- English → Chinese → English keeps the dialog open, correctly localizes
  control names, and preserves source text, source identity, output language,
  task content and approval bindings.
- Closing after a validation error works. Reopening and repeated close clicks
  do not submit a form, approve a plan or start execution.
- Narrow navigation retains setup, installation identity and sign-out actions;
  explanatory sidebar prose may be hidden without hiding those actions.

`test_vol20_r2_dialog_controls.py` loads the shipped HTML, CSS and complete JS
in a real browser with explicitly synthetic HTTP responses. It exercises
import, reading, task draft, project edit, setup guide and installation identity
through their visible control dispatch. The fixture has a 720px inner viewport;
the earlier 20,000px height used for width geometry alone could not establish
vertical close-control reachability. It uses a browser task queue rather than
timer polling; the measurement deadline is unchanged. Process/provider tests,
native key input and packaged GUI checks retain their separate scopes.

The two supplied Owner screenshots contain an existing Close button, so they
are evidence of poor placement/discoverability, not proof of a missing DOM
element. Owner-reported restart readback PASS is preserved separately. An
assistant input-card request is not proof that the desktop client displayed it;
instructions and reply options must also appear in ordinary message text.

This change grants no new authority, creates no account, changes no schema and
does not rerun accepted business actions. Full validation and Owner acceptance
must be recorded from their actual results, not inferred from targeted tests.
