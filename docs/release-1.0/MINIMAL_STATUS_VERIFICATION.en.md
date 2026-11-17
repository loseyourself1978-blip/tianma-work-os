# Minimal task status, exact-host focus and English voice: verification

Scope: TWOS 1.0.11 / 101.59 and Nyra 1.0.8 / 108, November 17, 2026. Engineering evidence and Owner acceptance are separate. Public availability is determined by the matching GitHub Release.

## Actual causes and changes

The reported desktop instance was an older engineering Nyra bound to a different exact TWOS installation. The installed TWOS correctly refused to adopt that unrelated helper. After the Owner normally quit it and launched the installed companion, the Owner confirmed that a character click returned to the installed workbench. This explains that observed installation mismatch; it does not explain every historical missed click.

Two additional implementation problems were confirmed in source: default task presentation depended on control-channel rows, including ended rows, and character focus used that same task-control client. An operation diagnostic could also remain in the character's upper detail overlay. The amendment separates authenticated read-only activity, host-only focus and task mutation. The default bubble includes only current observed activity, uses bounded stale grace, and hides on confirmed idle/terminal state. It no longer displays persistent diagnostics above the character. Actual drafts and uncertain-send records remain intact.

A real anonymous ChatGPT engineering conversation exposed another gap: `/uc/…` activity was rejected by the saved-target URL filter. A separate exact-host read-only activity URL accepts that observed route without making it a restorable handoff or editable task. Generic provider landing-page titles now use a localized activity placeholder, such as “Replying”; no summary model or earlier message supplies the title.

Host focus does not require a task, turn or edit grant. It still verifies the same user, exact signed application, live peer and host instance. I/O and peer verification run off the UI thread. The host restores its own workbench and checks actual visibility, deminiaturization, active/key state and occlusion. No other installation is launched by display name. Pending operations release on bounded completion/error. Mutation permissions and task/turn/request binding remain strict.

## Real final-package observations

| Requirement | Recorded result | Boundary |
| --- | --- | --- |
| Left, right and simultaneous activity | Actual isolated ChatGPT replies and an owned local Codex waiting command appeared in the final embedded companion. Both sides remained distinguishable in two compact lines. | Non-sensitive engineering samples only; no accepted Owner task was replayed. |
| Ended work disappears | The final embedded sample reached its observed terminal and the bubble closed. The final standalone sample showed real left-side activity and then closed on idle. | Executor completion is not business verification or Owner acceptance. |
| Read-only state survives unavailable controls | During an eight-second controlled outage of only the control socket, trusted activity and the visible bubble remained. The socket was restored. | Status and task-mutation authority remain separate. |
| Observation interruption | A real `CODEX_SERVICE_INTERRUPTED` interval produced bounded unknown state, then recovery and a real terminal. | Unknown was never converted to idle or PASS. An earlier gap lacked its raw service error and retains that limitation. |
| Physical character clicks | The matching final pair recorded 24 character-click results: 23 confirmed visible returns, 13–661 ms, median 58 ms; one unconfirmed result after 1,423 ms. The Owner reported that all requested clicks displayed TWOS. | This is not 24/24 confirmed or a claim that every click completed within one second. Individual quick/minimized/hidden scene labels were not independently recorded. |
| Host restart and hidden window | The standalone helper safely rebound to the normally restarted exact host. A subsequent OS mouse event restored the hidden workbench with a confirmed 100 ms result. | This event is synthetic and is excluded from the physical-click count. No separately measured multi-display, Space or fullscreen result is asserted. |
| Existing controls and appearance | Focused compatibility checks cover existing task binding, drafts, input/IME mechanisms, Steer/Queue, Stop, actions, wardrobe, transparent stage and resource integrity. | Prior physical IME/Steer/Stop evidence retains its original version and scope; it is not relabelled as repeated final-package physical testing. |

One earlier activity run had a hidden companion despite real host states. It is retained as incomplete visual evidence, with the visibility-change cause unproven. Later visible runs and final-package observations are recorded separately. Original sandbox, fixture and partial failures are retained; they are not added to a complete PASS.

## Voice and assets

The two products contain the same pinned Nyra code/resources. All five outfit portraits match the final runtime by SHA-256. Chinese remains the same 13 Tian / Xiaotian 1413 recordings, byte for byte. English has 13 matching offline tiny-voca F2 American English clips. All 26 language/action files decode; English clips are finite, non-silent PCM with no clipped samples. Actual English preview and an action cue reached the native audio player. These checks do not substitute for the Owner's listening preference.

The app contains approximately 1.6 MB of English WAV cues, upstream notices and provenance, with no speech model, model download, inference service or new billing. No conversation text is synthesized or sent to a speech provider. Explicit imported clips and sound/mute/cooldown behavior remain supported.

## Complete regression

One complete matching serial TWOS gate: 1,879 passed, one explicitly retained historical skip, zero failures. All 38 actual Safari measurements began and ended visible. Runtime and frozen input hashes were unchanged. Earlier partial/failure runs are preserved and are not combined into this result. Duration: 6482 seconds.

Standalone Nyra: 34 tests passed in one complete run after preserving an earlier sandbox-limited attempt. Matching signed-candidate compatibility: 34 passed. Publication documents, guide links and media are updated and checked after the frozen full gate; those later checks are separate from its complete result.

## Identity and release boundary

- TWOS runtime source: `4f29264ea9d156a671ef4d512f22430d3f875c19`.
- TWOS runtime input SHA-256: `f8603ab6487a913dab348e4c04dfcc41d9255b09836401b25e1d150b2db63ac1`.
- TWOS DMG SHA-256: `326f13b3925b3d8300328855aac74e213b2e4deb7cdc6f1912af43f3cc064240`.
- Nyra source: `bb60b2000b8d5a25c7234c7e1741b111d66d346c`.
- Nyra DMG SHA-256: `6f14ebdf588cfcbc98c5072ff2bade8df4e0ec77ca6bc19952e8cd976f09df16`.

Both matching applications and DMGs have accepted notarization receipts, stapling and Gatekeeper checks. Exact IDs are in `release.json`. The installed Owner applications are not replaced by engineering. Original acceptance and failure records remain preserved. New Owner acceptance is not granted by this report.

AI Team R0 remains an external read-only reuse/design deliverable. No R1 implementation, business-model team run, new payment channel, App Store restructuring or artwork remake is included.
