# Nyra: minimal activity and return to TWOS

TWOS 1.0.11 / 101.59. Public availability is determined by the matching GitHub Release.

> **Current update: minimal activity bubble, independent host focus and offline English voice.** [Instructions](MINIMAL_STATUS_AND_FOCUS.en.md) · [Actual verification and limits](MINIMAL_STATUS_VERIFICATION.en.md). The default bubble closes when no work is active; task mutations still require their separate authorization.

## What appears below Nyra

The compact bubble shows current observed work only: a bounded task title, provider and real state. Two active sides occupy one line each, marked L/R; long titles truncate before they can hide the state. No task is summarized by another model. Confirmed idle, completed, failed or cancelled work closes the bubble. A short observation gap shows Checking / status awaiting update, disables task actions, and expires rather than preserving an old task indefinitely. An available read-only status feed can show activity even when task-control authorization or its connection is unavailable.

Hover reveals the existing pencil and Stop controls. For two tasks, the selector identifies the action target; a line click focuses that exact task when its binding is available. If the target cannot be verified, a short notice explains that it needs an update; the action is not silently redirected. Ended owned drafts remain accessible from Nyra's edit-input menu without an idle bubble. Explicitly hiding task labels remains respected.


Anonymous ChatGPT `/uc/…` conversations can supply read-only activity. This does not make them saved handoff targets or grant edit/stop rights. The current-page observer reports activity only, without reading reply text. Codex observation reasons distinguish a lost connection, an interrupted service stream and an unconfirmed run; these do not imply idle or successful completion.

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

See the [verification record](MINIMAL_STATUS_VERIFICATION.en.md) for final-package activity/hiding, control outage, restart and click evidence. Of 24 actual character-click records, 23 confirmed visibility in 13–661 ms; one was unconfirmed after 1,423 ms. The Owner reported all displayed. This does not claim every click was subsecond or unmeasured scenes passed.

## English voice update

English uses 13 bundled tiny-voca F2 offline cues; Chinese Tian and explicit imports are preserved. See [voice details](ENGLISH_VOICE.en.md). No task text, synthesis service or model runtime is added.

Generic provider landing-page titles are not task names. When a current activity has no specific title, Nyra uses a localized activity placeholder; it never generates a summary or borrows an earlier message.
