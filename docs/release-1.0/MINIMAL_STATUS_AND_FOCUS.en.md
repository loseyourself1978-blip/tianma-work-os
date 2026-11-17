# Nyra: minimal activity and return to TWOS

Candidate identity: 1.0.11 / build 101.59. Not yet published.

Candidate amendment: NYRA-MINIMAL-STATUS-FOCUS-AND-R0-BOUNDARIES-R1. Verification and publication are pending; this is not a new public download or an Owner acceptance receipt.

## What appears below Nyra

The compact bubble shows current observed work only: a bounded task title, provider and real state. Two active sides occupy one line each, marked L/R; long titles truncate before they can hide the state. No task is summarized by another model. Confirmed idle, completed, failed or cancelled work closes the bubble. A short observation gap shows Checking / status awaiting update, disables task actions, and expires rather than preserving an old task indefinitely. An available read-only status feed can show activity even when task-control authorization or its connection is unavailable.

Hover reveals the existing pencil and Stop controls. For two tasks, the selector identifies the action target; a line click focuses that exact task when its binding is available. If the target cannot be verified, a short notice explains that it needs an update; the action is not silently redirected. Ended owned drafts remain accessible from Nyra's edit-input menu without an idle bubble. Explicitly hiding task labels remains respected.

## Return with one character click

Clicking the character requests the exact authenticated running TWOS workbench, even when there is no task or editing permission. A drag only moves Nyra. Task controls do not trigger character focus. Host restoration checks that the intended window is visible, not minimized, active and key; an activation API returning true alone is insufficient.

The new host-only focus socket is independent of the task-control socket. It accepts only focus metadata, not a task target, draft or command. Same-user, exact application/path, signature, live peer and host-instance verification remain required. Peer checks and I/O stay off the UI thread. An old host may use the bounded existing no-target focus request; unsupported or unconfirmed behavior is reported, never claimed successful.

If another installation's Nyra is running, use that Nyra's own Quit menu, then Show Nyra in the intended installed TWOS. Do not delete profiles or force-kill applications. Embedded Nyra may revalidate its fixed signed parent after a restart/update; standalone Nyra never silently selects a different installation or gains editing authority.

## Feedback, drafts and permissions

Connection/focus errors are short localized feedback for the current action and available in TWOS → More → Nyra status. There is no persistent diagnostic banner above the character. A generic connection failure does not claim that input was retained when no editing occurred. Actual draft recovery remains intact and separate; an uncertain send is never replayed.

Read-only status, host focus and task mutation are separate capabilities. Task actions additionally match the authenticated host, current status session/run, exact opaque target, permission and request identity. A title match alone grants nothing. Old hosts missing the new status/action binding safely lose bubble actions instead of guessing a target; ordinary host focus and status remain separate.

The pencil retains keyboard focus, Chinese IME, cancel and draft behavior. Steer/Queue, unsent-edit boundaries and permissions remain TWOS-controlled. Stop fences the selected task's queued/relay successors first, then requests its exact interruption. Stopping is not cancellation; after a true terminal the default activity bubble closes. The final result or an unconfirmed stop is inspected in TWOS. No approval, shell, expanded directory or control of an official-client-owned run is granted to Nyra.

The status channel contains bounded on-screen titles and minimal state/opaque IDs, not message bodies or files. The user-control channel carries only deliberately edited text/actions. The host-only focus request carries no task content. Hide labels before sharing a screen if needed.

## Verification boundary

A new candidate still requires real left/right/both activity and terminal hiding, control-outage behavior, host restart, and twenty real single-click observations with scene and latency. The warm target is at most one second, not an asserted test result. Full-screen/Space/multiple-display coverage must state what was actually observed. Prior click or protocol PASS evidence cannot replace the new candidate's GUI evidence.
