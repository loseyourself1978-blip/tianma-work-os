# Vol.19 19.4 Security / Docs / Release Hardening Contract v0.1

> Historical Vol.19 record. For current download identity, installation and schema, see the [Owner Guide](../OWNER_GUIDE.md). Status statements below describe this record's original gate.

Status: IMPLEMENTED / OWNER ACCEPTANCE PENDING. Only the Owner can accept 19.4.
Baseline: main `749f2c5de0928af631976ac4b5e05bfe44fa9ec2`, origin/main
`3cf914b6c5667059923ab209f8e9008b33a05cef`, clean 9 ahead / 0 behind.
Application remains 0.17.0; schema remains vol19.005. Accepted 19.1–19.3 remain closed.

19.4 audits authentication, local network, filesystem, subprocesses, Owner
approval, tool/provider setup, recovery, web rendering and tracked release content.
Every HIGH/RELEASE_BLOCKER must be resolved. MEDIUM findings require correction
or a concrete nonblocking disposition. Findings remain visible in the audit.

Accept != Apply != Stage != Commit != Push. No automatic execution, hidden
approval inheritance, Force, tag, source Push or 19.5 work is authorized.
Configured Git Commit hooks remain part of explicitly confirmed local Commit.

VOL19-19.2B-UI-01 must show completed Review Commit as neutral/disabled, suppress
duplicate requests, and require a new review when material dependencies change.
Commit confirmation guards remain authoritative and unchanged in strength.
VOL19-19.3-UX-01 disposition: MINIMAL_DISCOVERABILITY_IMPROVEMENT. Keep the existing
single-action dropdown with one explanatory sentence and explicit Owner docs;
no page redesign or simultaneous destructive actions.

The Owner entry point is [Owner Guide](../OWNER_GUIDE.md). Distribution is a
versioned deterministic macOS source archive from exact clean Git HEAD, with a
separate manifest containing full SHA, versions, commit-derived build time,
components, content hashes, artifact SHA-256, platform and limitations.
Untracked files are never package inputs. Sensitive/prohibited tracked content
fails the build; exact reviewed synthetic false positives are recorded by hash.
The archive includes bootstrap, runtime/UI, Owner guide and these technical records.

Automated artifact acceptance uses independent extracted source, HOME, runtime,
data and workspace. It must demonstrate zero initial Owner, First Run, Owner,
workspace, Task, restart and login persistence, with zero provider/Run/delivery
activity. Live Owner acceptance uses persistent isolated artifact stages and
never normal Owner data. Credentials belong only in the private acceptance guide.

Required final gate: `.venv/bin/python -m pytest -q`, zero failures/skips/xfail,
serial focused/regression groups, syntax/compile/diff checks, resource/journal
reconciliation, source scan, independent archive inspection/hash and install proof.
Exactly one implementation commit after green validation. No amend, Push or tag.
TWOS 1.0 RC remains NOT COMPLETE; 1.0.0 NOT RELEASED; 19.5 NOT STARTED.
