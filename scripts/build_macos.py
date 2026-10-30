#!/usr/bin/env python3
"""Build the macOS desktop candidate in a fresh builder environment.

Release builds require a clean Git commit. Development snapshots are explicitly
labelled, hashed inputs and cannot be mistaken for an immutable release commit.
No credential directories or development databases are collected.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.run([str(item) for item in args], check=True, **kwargs)


def sha(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def source_inputs(root):
    result = []
    for folder in ("twos_runtime", "static_cockpit", "packaging/macos"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts and path.suffix in {".py", ".js", ".html", ".css", ".svg", ".png", ".ico", ".swift", ".lock", ".json", ".md", ".txt", ".wav"}:
                result.append(path.relative_to(root).as_posix())
    result += ["scripts/twos_bootstrap.py", "scripts/build_macos.py", "scripts/sign_macos.py", "scripts/build_nyra.py"]
    return sorted(result)


def native_dependency_audit(app):
    versions = {}
    magic = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}
    for path in sorted(app.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) not in magic:
                continue
        metadata = subprocess.check_output(["otool", "-l", str(path)], text=True)
        minima = re.findall(r"\bminos (\d+\.\d+(?:\.\d+)?)", metadata)
        minima += re.findall(r"LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version (\d+\.\d+(?:\.\d+)?)", metadata)
        versions[path.relative_to(app).as_posix()] = minima
        links = subprocess.check_output(["otool", "-L", str(path)], text=True).splitlines()[1:]
        for link in links:
            target = link.strip().split(" (")[0]
            if target.startswith("/") and not target.startswith(("/System/Library/", "/usr/lib/")):
                raise RuntimeError("External non-system native dependency: " + target)
    minimum = max([(13, 0)] + [tuple(map(int, item.split("."))) for values in versions.values() for item in values])
    return {"minimum_macos": ".".join(map(str, minimum)), "native_binaries": versions, "external_developer_linkages": []}


def third_party_notices(resources):
    folder = resources / "Third Party Notices"
    folder.mkdir()
    lines = ["Runtime and build dependency notices. Build tools are listed for attribution; their inclusion here does not mean they are shipped as runtime code."]
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        lines.append(f"{name} {distribution.version}")
        for file in distribution.files or ():
            if ".." in file.parts or not any(word in file.name.lower() for word in ("license", "copying", "notice")) or file.suffix in (".py", ".pyc"):
                continue
            actual = Path(distribution.locate_file(file))
            if actual.is_file():
                destination = folder / name / str(file)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(actual, destination)
    python_license = Path(sys.base_prefix) / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Python license text is required in the distributed runtime")
    shutil.copy2(python_license, folder / "Python-LICENSE.txt")
    (folder / "README.txt").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--development-snapshot", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        parser.error("This candidate builder supports Apple Silicon macOS only.")
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if dirty and not args.development_snapshot:
        parser.error("Commit the reviewed source first; release artifacts require clean immutable inputs.")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    names = source_inputs(ROOT)
    if not dirty:
        tracked = set(subprocess.check_output(["git", "ls-tree", "-r", "--name-only", commit], cwd=ROOT, text=True).splitlines())
        names = [name for name in names if name in tracked]
    payloads = {name: (ROOT / name).read_bytes() if dirty else subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=ROOT) for name in names}
    from build_release import scan, validate_path
    for name, payload in payloads.items():
        validate_path(name)
        scan(name, payload)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    source = output / "source-input"
    for name in names:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads[name])
    version = (source / "twos_runtime/__init__.py").read_text().split('__version__ = "')[1].split('"')[0]
    provenance = {"version": version, "source_commit": commit, "source_clean": not bool(dirty),
                  "source_identity": "development-snapshot" if dirty else "git-commit", "source_input_sha256": digest,
                  "input_hashes": hashes, "architecture": "arm64", "python": platform.python_version(),
                  "macos": platform.mac_ver()[0], "bundle_identifier": "com.tianma.workos", "build_version": "101.51",
                  "public_ga": False, "signing": "ad-hoc-local-validation-only"}
    (output / "source-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (output / "builder-dependencies.txt").write_bytes(subprocess.check_output([sys.executable, "-m", "pip", "freeze", "--all"]))
    dist, build = output / "frozen", output / "build"
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "twos-service",
         "--distpath", dist, "--workpath", build, "--specpath", output, "--paths", source,
         "--collect-submodules", "twos_runtime", "--collect-submodules", "uvicorn", "--collect-submodules", "sqlalchemy.dialects.sqlite",
         "--hidden-import", "scripts.twos_bootstrap", "--exclude-module", "pytest", "--exclude-module", "tkinter",
         "--add-data", str(source / "static_cockpit") + ":static_cockpit", source / "packaging/macos/service_entry.py"], cwd=source)
    stage = output / "volume"
    app = stage / "Tianma Work OS.app"
    contents = app / "Contents"
    resources = contents / "Resources"
    resources.mkdir(parents=True)
    (contents / "MacOS").mkdir()
    shutil.copytree(dist / "twos-service", resources / "engine", symlinks=True)
    launcher_source = output / "TianmaLauncher.swift"
    launcher_source.write_text("\n".join((source / "packaging/macos" / name).read_text() for name in
        ("CodexAttachments.swift", "CodexTelemetry.swift", "NativeCodex.swift", "IntegratedWorkbench.swift", "PairedWorkflow.swift", "TianmaLauncher.swift")))
    run(["xcrun", "swiftc", "-swift-version", "5", "-module-cache-path", output / "swift-module-cache", "-O", "-target", "arm64-apple-macosx13.0", "-framework", "AppKit", "-framework", "LocalAuthentication", "-framework", "WebKit",
         launcher_source, "-o", contents / "MacOS/TianmaLauncher"])
    run(["xcrun", "swiftc", "-framework", "AppKit", source / "packaging/macos/MakeIcon.swift", "-o", output / "make-icon"])
    run([output / "make-icon", output / "TWOS.iconset"])
    run(["iconutil", "-c", "icns", output / "TWOS.iconset", "-o", resources / "TWOS.icns"])
    run([sys.executable, source / "scripts/build_nyra.py", "--source", source / "packaging/macos/nyra", "--destination", contents / "Helpers/TWOS Nyra.app", "--cache", output / "nyra-swift-cache"])
    audit = native_dependency_audit(app)
    (output / "native-dependency-audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    provenance["minimum_macos"] = audit["minimum_macos"]
    (output / "source-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    third_party_notices(resources)
    info = {"CFBundleName": "Tianma Work OS", "CFBundleDisplayName": "Tianma Work OS", "CFBundleExecutable": "TianmaLauncher",
            "CFBundleIdentifier": "com.tianma.workos", "CFBundlePackageType": "APPL", "CFBundleShortVersionString": version,
            "CFBundleVersion": provenance["build_version"], "CFBundleIconFile": "TWOS.icns", "LSApplicationCategoryType": "public.app-category.productivity",
            "LSMinimumSystemVersion": audit["minimum_macos"], "NSHighResolutionCapable": True,
            "TWOSSourceCommit": commit, "TWOSSourceInputSHA256": digest,
            "TWOSSourceIdentity": provenance["source_identity"],
            "NSMicrophoneUsageDescription": "Use the microphone only when you choose voice input on ChatGPT. / 仅在你选择 ChatGPT 语音输入时使用麦克风。",
            "NSCameraUsageDescription": "Use the camera only when you choose it on ChatGPT. / 仅在你于 ChatGPT 中选择相机时使用。", "NSHumanReadableCopyright": "Tianma Work OS"}
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    shutil.copy2(output / "source-provenance.json", resources / "source-provenance.json")
    # Normalize distribution permissions; no world/group-writable executable path.
    for path in [stage, *stage.rglob("*")]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or os.access(path, os.X_OK) else 0o644)
    run(["codesign", "--force", "--deep", "--sign", "-", app])  # local test only, never public signing
    run(["codesign", "--verify", "--deep", "--strict", app])
    (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
    (stage / "Install Tianma Work OS.txt").write_text(
        "Tianma Work OS " + version + "\n\nDrag Tianma Work OS to Applications. Open it from Applications and follow First Run.\n"
        "LOCAL ENGINEERING CANDIDATE: public Developer ID signing, notarization and Owner acceptance are pending.\n"
        "Do not use this candidate to bypass macOS Gatekeeper.\n\n"
        "将 Tianma Work OS 拖入 Applications（应用程序），从应用程序启动并完成首次设置。\n"
        "仅供本机工程验证：公开签名、公证及 Owner 验收尚未完成。不要用此候选绕过 macOS Gatekeeper。\n")
    manifest = {}
    for path in sorted(app.rglob("*")):
        relative = path.relative_to(app).as_posix()
        if path.is_symlink():
            if not path.resolve().is_relative_to(app.resolve()):
                raise RuntimeError("Bundle symlink escapes app: " + relative)
            manifest[relative] = {"symlink": os.readlink(path)}
        elif path.is_file():
            if path.name in ("auth.json", ".env", "id_rsa", "id_ed25519") or any(item in path.parts for item in (".codex", ".ssh", ".git", "node_modules")):
                raise RuntimeError("Forbidden developer/credential payload: " + relative)
            manifest[relative] = {"sha256": sha(path), "size": path.stat().st_size}
    (output / "installer-manifest.json").write_text(json.dumps({"app": app.name, "files": manifest}, indent=2) + "\n")
    dmg = output / f"Tianma-Work-OS-{version}-build-{provenance['build_version']}.dmg"
    run(["hdiutil", "create", "-volname", "Tianma Work OS", "-srcfolder", stage, "-format", "UDZO", "-ov", dmg])
    (output / "SHA256SUMS").write_text("".join(f"{sha(output / name)}  {name}\n" for name in
        (dmg.name, "installer-manifest.json", "source-provenance.json", "builder-dependencies.txt")))
    (output / "release-receipt.json").write_text(json.dumps({**{key: value for key, value in provenance.items() if key != "input_hashes"},
        "artifact": dmg.name, "sha256": sha(dmg), "size": dmg.stat().st_size, "notarization": "NOT_EXECUTED",
        "owner_acceptance": "NOT_EXECUTED", "official_download": None}, indent=2) + "\n")
    print(json.dumps({"artifact": str(dmg), "sha256": sha(dmg), "size": dmg.stat().st_size}))


if __name__ == "__main__":
    main()
