#!/usr/bin/env python3
"""Build/inspect the macOS source distribution from a clean exact Git HEAD (stdlib only)."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone


GUIDE = "docs/OWNER_GUIDE.md"
DOC_PREFIX = "docs/runtime/VOL19_19_4_"
REQUIRED = {"README.md", "requirements.txt", "start-twos", GUIDE,
            "scripts/twos_bootstrap.py", "scripts/build_release.py", "scripts/release_scan_allowlist.json",
            "twos_runtime/app.py", "twos_runtime/db.py", "twos_runtime/__init__.py",
            "static_cockpit/vol12_static_mvp/twos_command_center.html"}
FORBIDDEN_PARTS = {".git", ".venv", "venv", ".env", ".codex", ".aws", ".ssh",
                   "__pycache__", ".pytest_cache", "node_modules", "backups",
                   "acceptance", ".phase63a-worktree"}
SECRET_PATTERNS = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "provider-key": re.compile(rb"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{32,}"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"),
    "aws-key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "credential-assignment": re.compile(rb'''(?i)(?:api_key|access_token|refresh_token|client_secret|password|token)["']?\s*[=:]\s*["'][^"'\r\n]{8,}["']'''),
}
LIMITATIONS = [
    "Source-based macOS fresh-install distribution; signed/notarized DMG and Windows/Linux acceptance are not established.",
    "Python 3.11–3.13 and dependency installation are required; dependencies are not bundled or locked.",
    "1.0.0 supports fresh installation and same-version backup/restore only; 0.17.0 upgrades and cross-version restore are outside scope.",
    "External credentialed Git-host Push acceptance is not established.",
    "Live multi-model aggregation and email/calendar integration are not established.",
    "LDD live broker execution is not authorized. Publication identity is established by the canonical Release receipt; build success is not Owner Acceptance.",
]


class ReleaseError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def validate_path(name: str) -> None:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
            or str(path) != name or any(ord(c) < 32 for c in name)
            or any(part.lower() in FORBIDDEN_PARTS for part in path.parts)
            or any(part.lower().endswith(".twos-backup") for part in path.parts)
            or path.name.lower() in {"auth.json", "credentials.json", "setup-authorization.txt"}
            or re.search(r"(?i)(?:\.sqlite(?:3)?(?:-.*)?|\.db|\.py[co]|\.log|\.pid|\.tmp|\.env(?:\..*)?)$", name)):
        raise ReleaseError("Prohibited release path: " + name)


def selected(name: str) -> bool:
    return (name in REQUIRED or name.startswith("twos_runtime/")
            or name.startswith("static_cockpit/")
            or name.startswith(DOC_PREFIX) and name.endswith(".md"))


def scan(name: str, data: bytes, *, strict: bool = True) -> list[str]:
    if data.startswith(b"SQLite format 3\0"):
        raise ReleaseError("Database content rejected: " + name)
    allowed = json.loads(Path(__file__).with_name("release_scan_allowlist.json").read_bytes())
    hits = []
    for rule, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(data):
            disposition = next((item["disposition"] for item in allowed
                if item["path"] == name and item["rule"] == rule
                and item["match_sha256"] == digest(match.group())), None)
            if disposition is None:
                raise ReleaseError("Secret scan rejected " + name + " (" + rule + ")")
            hits.append(rule + ": " + disposition)
    return hits


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    executable = shutil.which("git")
    if not executable:
        raise ReleaseError("Git is required to build an exact source release.")
    names = {"PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE"}
    environment = {key: value for key, value in os.environ.items() if key in names}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0")
    result = subprocess.run([executable, "-c", "core.fsmonitor=false", "-C", str(repo), *args], env=environment,
                            input=input_bytes, capture_output=True, timeout=120)
    if result.returncode:
        raise ReleaseError("Git source verification failed: " + args[0])
    return result.stdout


def artifact_identity(version: str, sha: str) -> str:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ReleaseError("Invalid application version.")
    suffix = "-rc19.4" if tuple(map(int, version.split("."))) < (1, 0, 0) else ""
    return f"twos-{version}{suffix}-{sha[:12]}"


def read_commit(repo: Path) -> tuple[dict, dict[str, tuple[bytes, int]], list[dict]]:
    if git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise ReleaseError("Tracked source/index must be clean before packaging.")
    sha = git(repo, "rev-parse", "HEAD").decode().strip()
    epoch = int(git(repo, "show", "-s", "--format=%ct", sha))
    files = {}
    fixtures = []
    # Read the exact committed tree/blobs. Git archive honors export-ignore and
    # export-subst; those attributes must not hide tracked secrets or rewrite
    # release bytes. Batch cat-file avoids reading arbitrary working-tree state.
    entries = []
    for row in git(repo, "ls-tree", "-rz", sha).split(b"\0"):
        if not row:
            continue
        header, raw_name = row.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        name = raw_name.decode("utf-8")
        validate_path(name)
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ReleaseError("Source links/special files are prohibited: " + name)
        entries.append((name, mode, oid))
    content = io.BytesIO(git(repo, "cat-file", "--batch",
        input_bytes=("\n".join(oid for _name, _mode, oid in entries) + "\n").encode("ascii")))
    for name, mode, oid in entries:
        found, kind, size = content.readline().decode("ascii").strip().split()
        if found != oid or kind != "blob":
            raise ReleaseError("Committed blob identity mismatch.")
        data = content.read(int(size))
        if len(data) != int(size) or content.read(1) != b"\n":
            raise ReleaseError("Committed blob framing mismatch.")
        tracked_path = repo / name
        try:
            metadata = tracked_path.lstat()
            linked_parent = any(parent.is_symlink() for parent in tracked_path.parents if parent != repo and repo in parent.parents)
            if (linked_parent or not stat.S_ISREG(metadata.st_mode)
                    or bool(metadata.st_mode & 0o111) != (mode == "100755")
                    or tracked_path.read_bytes() != data):
                raise ReleaseError("Tracked source must match exact HEAD: " + name)
        except OSError as exc:
            raise ReleaseError("Tracked source is unavailable: " + name) from exc
        hits = scan(name, data, strict=selected(name))
        if hits:
            fixtures.append({"path": name, "rules": hits, "included": selected(name)})
        if selected(name):
            files[name] = (data, 0o755 if mode == "100755" else 0o644)
    missing = REQUIRED - files.keys()
    if missing:
        raise ReleaseError("Missing required release components: " + ", ".join(sorted(missing)))
    version = re.search(rb'__version__ = "([^"]+)"', files["twos_runtime/__init__.py"][0]).group(1).decode()
    schema = re.search(rb'LATEST_SCHEMA = "([^"]+)"', files["scripts/twos_bootstrap.py"][0]).group(1).decode()
    metadata = {"source_git_sha": sha, "application_version": version, "schema_version": schema,
                "artifact_identity": artifact_identity(version, sha),
                "build_time": datetime.fromtimestamp(epoch, timezone.utc).isoformat(),
                "build_time_basis": "source commit time (reproducible SOURCE_DATE_EPOCH)",
                "supported_platform": "macOS source distribution; Python 3.11–3.13",
                "known_release_limitations": LIMITATIONS}
    files["RELEASE_SOURCE.json"] = (encoded(metadata), 0o644)
    return metadata, files, fixtures


def inspect(artifact: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_bytes())
    raw = artifact.read_bytes()
    if digest(raw) != manifest["sha256"] or artifact.name != manifest["artifact"]:
        raise ReleaseError("Final artifact identity/hash mismatch.")
    files = {}
    identity = manifest["artifact_identity"]
    sha = manifest["source_git_sha"]
    if (not isinstance(identity, str) or not re.fullmatch(r"twos-[0-9]+\.[0-9]+\.[0-9]+(?:-rc19\.4)?-[a-f0-9]{12}", identity)
            or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha)
            or identity not in {artifact_identity(manifest['application_version'], sha),
                                f"twos-{manifest['application_version']}-rc19.4-{sha[:12]}"}
            or artifact.name != identity + ".tar.gz"):
        raise ReleaseError("Invalid release artifact/source identity.")
    source = None
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive.getmembers():
            validate_path(member.name)
            if not member.name.startswith(identity + "/") or not member.isfile():
                raise ReleaseError("Unexpected archive member/type.")
            name = member.name[len(identity) + 1:]
            validate_path(name)
            if name in files or not (selected(name) or name == "RELEASE_SOURCE.json"):
                raise ReleaseError("Unexpected/duplicate package content: " + name)
            if member.mode not in {0o644, 0o755} or member.uid or member.gid:
                raise ReleaseError("Unexpected package permissions/ownership.")
            data = archive.extractfile(member).read()
            scan(name, data)
            files[name] = {"sha256": digest(data), "mode": member.mode, "size": len(data)}
            if name == "RELEASE_SOURCE.json":
                source = json.loads(data)
    if (REQUIRED | {"RELEASE_SOURCE.json"}) - files.keys() or files != manifest["files"]:
        raise ReleaseError("Release content manifest mismatch.")
    if not isinstance(source, dict) or any(manifest.get(key) != value for key, value in source.items()):
        raise ReleaseError("Embedded source metadata mismatch.")
    required_metadata = {"source_git_sha", "artifact_identity", "application_version", "schema_version",
                         "build_time", "build_time_basis", "supported_platform", "known_release_limitations"}
    if source.keys() != required_metadata:
        raise ReleaseError("Embedded source metadata is incomplete.")
    return {"verified": True, "source_git_sha": source["source_git_sha"],
            "sha256": digest(raw), "file_count": len(files), "forbidden_content": 0}


def build(repo: Path, output: Path) -> tuple[Path, Path]:
    metadata, files, fixtures = read_commit(repo.resolve())
    output.mkdir(parents=True, exist_ok=True)
    identity = metadata["artifact_identity"]
    artifact = output / (identity + ".tar.gz")
    manifest_path = output / (identity + ".manifest.json")
    if artifact.exists() or manifest_path.exists() or artifact.is_symlink() or manifest_path.is_symlink():
        raise ReleaseError("Release outputs already exist; choose an empty output directory.")
    epoch = int(datetime.fromisoformat(metadata["build_time"]).timestamp())
    with tempfile.TemporaryDirectory(prefix="twos-release-", dir=output) as temporary:
        staging = Path(temporary) / "source"
        staging.mkdir()
        for name, (data, mode) in files.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(mode)
        staged_artifact = Path(temporary) / artifact.name
        with staged_artifact.open("xb") as stream, gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for name in sorted(files):
                    data, mode = files[name]
                    validate_path(name)
                    scan(name, (staging / name).read_bytes())
                    member = tarfile.TarInfo(identity + "/" + name)
                    member.size, member.mode, member.mtime = len(data), mode, epoch
                    archive.addfile(member, io.BytesIO(data))
        manifest = {**metadata, "artifact": artifact.name, "sha256": digest(staged_artifact.read_bytes()),
                    "included_top_level_components": sorted({name.split("/")[0] for name in files}),
                    "reviewed_scan_findings": fixtures,
                    "files": {name: {"sha256": digest(data), "mode": mode, "size": len(data)}
                              for name, (data, mode) in sorted(files.items())}}
        staged_manifest = Path(temporary) / manifest_path.name
        staged_manifest.write_bytes(encoded(manifest))
        inspect(staged_artifact, staged_manifest)
        # Exclusive publication prevents overwriting a previous artifact.
        os.link(staged_artifact, artifact)
        os.link(staged_manifest, manifest_path)
    inspect(artifact, manifest_path)
    return artifact, manifest_path


def release_receipt(repo: Path, artifact: Path, manifest_path: Path, *, tag: str, release_date: str) -> Path:
    """Seal publication metadata only for an annotated tag on the packaged commit.

    This prepares local assets; it neither creates a tag nor publishes anything.
    """
    verified = inspect(artifact, manifest_path)
    manifest = json.loads(manifest_path.read_bytes())
    version = manifest["application_version"]
    if tag != "v" + version:
        raise ReleaseError("Release tag must match the application version.")
    ref = "refs/tags/" + tag
    if git(repo, "cat-file", "-t", ref).strip() != b"tag":
        raise ReleaseError("A non-force annotated release tag is required.")
    commit = git(repo, "rev-parse", ref + "^{commit}").decode().strip()
    if commit != verified["source_git_sha"] or commit != git(repo, "rev-parse", "HEAD").decode().strip():
        raise ReleaseError("Release tag, artifact and HEAD must identify the same commit.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
        raise ReleaseError("Release date must be YYYY-MM-DD.")
    datetime.strptime(release_date, "%Y-%m-%d")
    receipt = artifact.parent / ("release-" + version + ".json")
    checksums = artifact.parent / "SHA256SUMS"
    if receipt.exists() or checksums.exists() or receipt.is_symlink() or checksums.is_symlink():
        raise ReleaseError("Release receipt/checksums already exist; never overwrite release assets.")
    payload = {"release": {"version": version, "commit": commit, "tag": tag,
        "artifact": artifact.name, "sha256": verified["sha256"], "release_date": release_date,
        "schema_version": manifest["schema_version"], "manifest": manifest_path.name,
        "canonical_source": "https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/" + tag}}
    with receipt.open("xb") as stream:
        stream.write(encoded(payload))
    with checksums.open("x") as stream:
        for path in (artifact, manifest_path, receipt):
            stream.write(digest(path.read_bytes()) + "  " + path.name + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--inspect", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--tag", help="Prepare a release receipt for this existing annotated tag.")
    parser.add_argument("--release-date", help="Explicit publication date, YYYY-MM-DD.")
    args = parser.parse_args()
    try:
        if args.inspect and args.manifest:
            print(json.dumps(inspect(args.inspect, args.manifest), sort_keys=True))
        elif args.output and not args.inspect:
            artifact, manifest = build(args.repo, args.output)
            result = {"artifact": str(artifact), "manifest": str(manifest)}
            if args.tag or args.release_date:
                if not args.tag or not args.release_date:
                    raise ReleaseError("Supply --tag and --release-date together.")
                result["release_receipt"] = str(release_receipt(args.repo, artifact, manifest,
                    tag=args.tag, release_date=args.release_date))
            print(json.dumps(result, sort_keys=True))
        else:
            parser.error("Use --output, or --inspect ARTIFACT --manifest MANIFEST.")
    except (ReleaseError, OSError, KeyError, tarfile.TarError, ValueError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
