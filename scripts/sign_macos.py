#!/usr/bin/env python3
"""Maintainer-only Developer ID / notarization pipeline. Secrets stay in Keychain.

Run only against an unpublished clean-commit candidate. Never changes a tag or
uploads to GitHub. A local ad-hoc signature is not accepted as Developer ID.
"""
import argparse
import json
from pathlib import Path
import subprocess


def run(args):
    subprocess.run([str(item) for item in args], check=True)


def signing_targets(app):
    """Nested code must be sealed before its containing bundle, including Nyra."""
    magics = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}
    targets = []
    for path in app.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir() and path.suffix in {".app", ".framework", ".xpc", ".appex"}:
            targets.append(path)
        elif path.is_file():
            with path.open("rb") as stream:
                if stream.read(4) in magics:
                    targets.append(path)
    return sorted(targets, key=lambda item: (-len(item.parts), str(item))) + [app]


def notarize(artifact, profile, receipt):
    result = subprocess.run(["xcrun", "notarytool", "submit", str(artifact),
        "--keychain-profile", profile, "--wait", "--output-format", "json"],
        text=True, capture_output=True)
    # Preserve Apple's actual response for both accepted and rejected submissions.
    receipt.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Notarization failed; see {receipt}: {result.stderr.strip()}")
    response = json.loads(result.stdout)
    if response.get("status") != "Accepted" or not response.get("id"):
        raise RuntimeError(f"Notarization was not Accepted; see {receipt}")
    return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--notary-profile", default="TWOS-NOTARY")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.identity.startswith("Developer ID Application: "):
        parser.error("Public direct distribution requires Developer ID Application.")
    input_app = args.app.resolve(strict=True)
    provenance = json.loads((input_app / "Contents/Resources/source-provenance.json").read_text())
    if provenance.get("source_clean") is not True:
        parser.error("Development snapshots cannot be published. Build from a clean reviewed commit.")
    if args.output.exists():
        parser.error("Use a new unpublished output directory; existing artifacts are immutable.")
    args.output.mkdir(parents=True)
    app = args.output / input_app.name
    run(["ditto", input_app, app])
    provenance["signing"] = "Developer ID Application; consult signed release receipt for notarization"
    (app / "Contents/Resources/source-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    # Sign each Mach-O and nested bundle from the inside out. No --deep signing.
    for target in signing_targets(app):
        run(["codesign", "--force", "--timestamp", "--options", "runtime", "--sign", args.identity, target])
    run(["codesign", "--verify", "--deep", "--strict", app])
    archive = args.output / "notarization.zip"
    run(["ditto", "-c", "-k", "--keepParent", app, archive])
    app_submission = notarize(archive, args.notary_profile, args.output / "app-notarization.json")
    # stapler validation must succeed even if notarytool returned a rejected job.
    run(["xcrun", "stapler", "staple", app])
    run(["xcrun", "stapler", "validate", app])
    run(["spctl", "--assess", "--type", "execute", "--verbose=4", app])
    # DMG creation/final notarization must use the newly stapled app, never reuse
    # the local candidate's checksum or receipt.
    stage = args.output / "volume"
    stage.mkdir()
    run(["ditto", app, stage / app.name])
    (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
    dmg = args.output / f"Tianma-Work-OS-{provenance['version']}.dmg"
    run(["hdiutil", "create", "-volname", "Tianma Work OS", "-srcfolder", stage, "-format", "UDZO", dmg])
    run(["codesign", "--timestamp", "--sign", args.identity, dmg])
    dmg_submission = notarize(dmg, args.notary_profile, args.output / "dmg-notarization.json")
    run(["xcrun", "stapler", "staple", dmg])
    run(["xcrun", "stapler", "validate", dmg])
    run(["spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose=4", dmg])
    import hashlib
    digest = hashlib.file_digest(dmg.open("rb"), "sha256").hexdigest()
    manifest = {}
    for path in sorted(app.rglob("*")):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                manifest[path.relative_to(app).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest_path = args.output / "installer-manifest.json"
    manifest_path.write_text(json.dumps({"files": manifest, "source_commit": provenance["source_commit"]}, indent=2) + "\n")
    (args.output / "source-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (args.output / "signed-release-receipt.json").write_text(json.dumps({"source_commit": provenance["source_commit"],
        "artifact": dmg.name, "sha256": digest, "signing_identity": args.identity,
        "notary_profile": args.notary_profile, "app_notarization_id": app_submission["id"],
        "dmg_notarization_id": dmg_submission["id"], "gatekeeper": "PASS", "owner_acceptance": "NOT_EXECUTED"}, indent=2) + "\n")
    names = [dmg.name, "installer-manifest.json", "source-provenance.json", "signed-release-receipt.json", "app-notarization.json", "dmg-notarization.json"]
    sums = []
    for name in names:
        with (args.output / name).open("rb") as stream:
            sums.append(hashlib.file_digest(stream, "sha256").hexdigest() + "  " + name + "\n")
    (args.output / "SHA256SUMS").write_text("".join(sums))


if __name__ == "__main__":
    main()
