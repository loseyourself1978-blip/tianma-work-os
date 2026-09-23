# Tianma Work OS 1.0.0

TWOS helps an Owner turn a development Task into reviewed, explicitly authorized
changes in a local workspace. Start with the **[Owner Guide](docs/OWNER_GUIDE.md)**.

## Download and verify

The canonical distribution entry is the [1.0.0 Release](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.0).
Download its `twos-1.0.0-<12-character-commit>.tar.gz`, matching `.manifest.json`,
`release-1.0.0.json` and `SHA256SUMS`. The release receipt identifies the full
commit, annotated `v1.0.0` tag, artifact SHA-256 and release date. A local archive
or an unavailable Release page is not proof of publication. Do not substitute
GitHub's automatically generated source archives for the verified package.

In the download folder run `shasum -a 256 -c SHA256SUMS` before extraction.
Keep the receipt and manifest with the archive. See the Owner Guide for the
complete verification and installation commands.

## Install and first delivery

This is a **macOS source distribution**, application **1.0.0**, schema
**vol20.001**, requiring Python 3.11–3.13 and Git. From the extracted source:

```sh
./start-twos
```

The launcher creates a new private Python environment and prints the local URL
and one-time First Run authorization code. Create your Owner, authorize a
dedicated workspace and finish setup. In **Projects and workspaces**, create a
Project and explicitly authorize its separate repository. Create a Task, select
its Project, then check and save **Guided Tool Setup** for that Project.
**Configure Artifact Verification** declares one output file and exact expected
text using the shipped verifier. Prepare, review, approve and explicitly start
First Delivery. Review the Result before separate Apply/Commit/Push decisions.
No external acceptance script is required for this first-delivery preset.

Keep the terminal open. Control-C stops TWOS; the same command restarts it.
Use independent empty data/runtime/log directories when another installation
already exists. Same-version backup/restore and explicit schema maintenance are
supported; 0.17.0 upgrades and cross-version restore remain outside scope.
Publication and technical test results do not declare Owner Acceptance or
permission for trading or clinical use.
