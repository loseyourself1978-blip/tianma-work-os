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
    # Sign each Mach-O from the inside out, then the app. No --deep signing.
    magics = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}
    for path in sorted(app.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                macho = stream.read(4) in magics
            if macho:
                run(["codesign", "--force", "--timestamp", "--options", "runtime", "--sign", args.identity, path])
    for framework in sorted(app.rglob("*.framework"), key=lambda item: len(item.parts), reverse=True):
        run(["codesign", "--force", "--timestamp", "--options", "runtime", "--sign", args.identity, framework])
    run(["codesign", "--force", "--timestamp", "--options", "runtime", "--sign", args.identity, app])
    run(["codesign", "--verify", "--deep", "--strict", app])
    archive = args.output / "notarization.zip"
    run(["ditto", "-c", "-k", "--keepParent", app, archive])
    run(["xcrun", "notarytool", "submit", archive, "--keychain-profile", args.notary_profile, "--wait", "--output-format", "json"])
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
    run(["xcrun", "notarytool", "submit", dmg, "--keychain-profile", args.notary_profile, "--wait", "--output-format", "json"])
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
        "notary_profile": args.notary_profile, "gatekeeper": "PASS", "owner_acceptance": "NOT_EXECUTED"}, indent=2) + "\n")
    names = [dmg.name, "installer-manifest.json", "source-provenance.json", "signed-release-receipt.json"]
    sums = []
    for name in names:
        with (args.output / name).open("rb") as stream:
            sums.append(hashlib.file_digest(stream, "sha256").hexdigest() + "  " + name + "\n")
    (args.output / "SHA256SUMS").write_text("".join(sums))


if __name__ == "__main__":
    main()
