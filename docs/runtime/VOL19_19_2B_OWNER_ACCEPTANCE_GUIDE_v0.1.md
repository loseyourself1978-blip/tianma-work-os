Use Log in. The temporary Owner account is already created. Do not use First Owner setup again.

# Vol.19 19.2B — Browser acceptance

Use the isolated acceptance URL and temporary credentials supplied in the
Owner handoff. Normal Owner data and normal project files are outside this
installation. The Git destination must be the supplied local bare remote.
Only the Owner can declare Acceptance PASS.

The intended Coding model is `gpt-6-astra`. The installed `codex-cli 0.153.4`
catalogue explicitly supports Extra high as `xhigh`; this is the guide's
default. `max` is also explicitly listed. `ultra` is excluded because its
installed description includes automatic delegation.

1. Log in.
2. Open the single **VOL19 19.2B — First Safe Delivery** Task.
3. Open **Guided Tool Setup**.
4. Confirm the detected Codex executable and CLI version.
5. Confirm readiness was not checked automatically: no saved check and no
   successful-check timestamp should exist initially.
6. Select **Check Codex Readiness** explicitly. This makes a bounded provider
   request for the selected configuration; it does not start the Task.
7. Confirm **Ready**, or report the exact displayed blocker.
   During the check, duplicate requests must be disabled. After success the
   Check button must be neutral and completed, with a successful timestamp.
8. Confirm the requested model is `gpt-6-astra`.
9. Confirm **Extra high (xhigh)** reasoning, or explicitly review another
   supported setting and check that exact selection again.
10. Select **Save Tool Setup** when this configuration has unsaved changes.
    Readiness checks connectivity; Save confirms the selected configuration.
    An unchanged saved configuration must not show Save as pending.
11. Refresh and confirm Tool Setup persists and Check remains completed.
    A material configuration change requires an explicit new check.
12. Select **Prepare First Delivery**.
13. Review the Task/version, workspace, source snapshot, model, reasoning,
    expected deliverable, independent Verification and execution boundary.
14. Confirm no Run started during preparation.
15. Approve the Instruction Pack explicitly.
16. Select **Start Codex Run**.
17. Review the final Run confirmation and its approved Pack and boundaries.
18. Confirm Start exactly once. Codex may change only the isolated Run
    workspace; it may not Commit or Push.
19. Observe truthful Coding activity.
20. Observe independent Verification.
21. Confirm **Result Available** after evidence settlement.
22. Select **Review Run Result** and inspect the result and Verification.
23. Explicitly **Accept for Delivery**. This accepts the captured result for
    delivery review; it does not Apply changes.
24. Review Candidate.
25. Review Apply Plan and its exact included paths.
26. Approve Apply Plan explicitly.
27. Explicitly Apply. This writes the approved changes into the authorized
    source workspace; it does not create a Commit.
28. Expand **Advanced — workspace, source and target paths** in the First
    Safe Delivery guide. Copy the current exact target path shown by the
    Apply journal; use the refreshed handoff's source path. Confirm that file contains exactly
    `TWOS VOL19 FIRST SAFE DELIVERY PASS` followed by one newline.
29. Confirm no Commit occurred automatically.
30. Select **Validate Applied Changes** as a separate action. Confirm Apply
    is **APPLIED** and post-Apply validation is **PASSED**, then select
    **Review Commit**. Refresh must preserve both states. Review Commit must
    stay blocked while either prerequisite is incomplete. If a Commit
    preflight blocker occurs, the completed Apply and validation must remain
    visible; resolve that displayed blocker before proceeding.
31. Approve the proposal and explicitly create the local Commit. This records
    the approved source changes in local Git history; it does not Push.
32. Confirm no Push occurred automatically.
33. Review Push Plan.
34. Confirm the destination is local-only `origin/main`, with no network Git
    remote, Force, tags or other branch.
35. Approve Push Plan explicitly.
36. Explicitly Confirm Push. This sends the exact approved Commit to the
    isolated local bare remote.
37. Confirm the receipt reports the exact verified remote SHA.
38. Confirm **Delivered**.
39. Refresh and verify the entire delivery state persists.
40. Confirm no second Run, Apply, Commit or Push happened automatically.
41. Check the workbench at approximately 1280px width.
42. Check it at approximately 390px width.
43. Confirm there is no blocking horizontal overflow and the current primary
    action remains reachable.
44. Confirm technical evidence remains under **Advanced**.

The required file starts as `TWOS VOL19 FIRST SAFE DELIVERY BEFORE` followed
by one newline. The independent deterministic verifier checks the exact final
content. Do not substitute a network Git remote or use any normal Owner files.

This acceptance does not close older-install migration, backup/restore,
signed installer/DMG, external credentialed Git-host Push, live multi-model
aggregation, email/calendar, release packaging, TWOS 1.0 RC or version 1.0.0.
19.2 remains open until Owner acceptance and its closeout are recorded.
