# Tianma Work OS

TWOS helps an Owner turn a development Task into reviewed, explicitly authorized
changes in a local workspace. Start with the **[Owner Guide](docs/OWNER_GUIDE.md)**
for installation, daily work, backup/recovery, security and troubleshooting.

The local release-preparation candidate is **1.0.0 / vol19.005**, distributed as
macOS source for **fresh installation**. Same-version 1.0.0 backup/restore is
supported; reuse of 0.17.0 data, upgrades and cross-version restore are outside
this release scope. Use new data/runtime/log directories; installation version
binding and incompatible-backup rejection remain enforced. Python 3.11–3.13
is required. From the extracted source folder:

```sh
./start-twos
```

Keep that terminal open. Press Control-C to stop; use the same command to restart.
The launcher prints the local URL and one-time First Run authorization code.
It creates its private runtime and data outside the source folder.

19.1 through 19.5 are PASS / OWNER ACCEPTED / CLOSED. The Owner explicitly
accepted the 19.5 candidate on 2026-09-22: implementation `94c026a2f3e1`,
application 0.17.0, schema vol19.005, with 1187 passing regression tests.
19.6 local release preparation is authorized by
`TWOS-V19.6-LOCAL-RELEASE-PREP-V1`. Its archive is named
`twos-1.0.0-<12-char-source-SHA>.tar.gz`, with an adjacent manifest. Historical
RCs remain unchanged. Version 1.0.0 is NOT RELEASED: local validation does not
authorize Push, tags, uploading or distribution. Final release remains pending.
