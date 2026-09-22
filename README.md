# Tianma Work OS

TWOS helps an Owner turn a development Task into reviewed, explicitly authorized
changes in a local workspace. Start with the **[Owner Guide](docs/OWNER_GUIDE.md)**
for installation, daily work, backup/recovery, security and troubleshooting.

The current release candidate is **0.17.0 / vol19.005**, distributed as macOS
source. Python 3.11–3.13 is required. From the extracted source folder:

```sh
./start-twos
```

Keep that terminal open. Press Control-C to stop; use the same command to restart.
The launcher prints the local URL and one-time First Run authorization code.
It creates its private runtime and data outside the source folder.

19.1 through 19.5 are PASS / OWNER ACCEPTED / CLOSED. The Owner explicitly
accepted the 19.5 candidate on 2026-09-22: implementation `94c026a2f3e1`,
application 0.17.0, schema vol19.005, with 1187 passing regression tests.
The acceptance candidate is complete; 19.6 release-contract preparation is next.
Version 1.0.0 is NOT RELEASED. This repository documentation closeout neither
rebuilds the accepted RC nor authorizes Push, tags or publication.
