"""Read-only, stdlib-only verifier launched by the sealed TWOS execution bridge.

Checks one Owner-declared exact artifact against a clean Git baseline. It does
not execute project code, interpret shell commands, contact providers, or judge
clinical/technical correctness beyond the declared bytes.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "LC_CTYPE"}}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="")
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                             "-C", str(root), *args], env=env, capture_output=True, timeout=10)
    if result.returncode:
        raise ValueError("Git boundary inspection failed")
    return result.stdout


def verify(contract, source, commit, worktree):
    target = PurePosixPath(contract.get("path", ""))
    if (contract.get("schema") != "twos.exact_artifact.v1" or target.is_absolute()
        or not target.parts or any(p in {"..", ".git", ".env", ".ssh", ".codex"} for p in target.parts)):
        raise ValueError("Invalid artifact contract")
    target_path = worktree.joinpath(*target.parts)
    safe = all(not p.is_symlink() for p in (target_path, *target_path.parents))
    expected = contract["expected_text"].encode("utf-8")
    metadata = target_path.lstat() if target_path.exists() else None
    content_ok = bool(safe and metadata and stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                      and metadata.st_size == len(expected) and target_path.read_bytes() == expected)
    changed = set(git(worktree, "diff", "--name-only", "-z", "HEAD").decode().strip("\0").split("\0"))
    # Include ignored additions: the contract authorizes one file, not just
    # changes visible in the default Git status view.
    changed.update(git(worktree, "ls-files", "--others", "-z").decode().strip("\0").split("\0"))
    changed.discard("")
    unexpected = sorted(changed - {str(target)})
    git_ok = (git(worktree, "rev-parse", "HEAD").decode().strip() == commit
              and git(source, "rev-parse", "HEAD").decode().strip() == commit
              and not git(worktree, "diff", "--cached", "--name-only")
              and not git(source, "status", "--porcelain"))
    remote_ok = git(worktree, "remote", "-v") == git(source, "remote", "-v")
    passed = content_ok and not unexpected and changed == {str(target)} and git_ok and remote_ok
    return {"schema": "twos.verification.v1", "verdict": "pass" if passed else "fail",
            "changed_files_checked": sorted(changed), "unexpected_files": unexpected,
            "exact_content": "pass" if content_ok else "fail", "tests": "not_applicable",
            "git_boundary": "pass" if git_ok else "fail", "remote_boundary": "pass" if remote_ok else "fail"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    if len(args.contract) > 4096:
        raise ValueError("Contract too large")
    payload = json.loads(base64.urlsafe_b64decode(args.contract))
    result = verify(payload["specification"], Path(payload["source"]), payload["commit"], Path.cwd())
    events = [{"type": "thread.started", "thread_id": "twos-exact-artifact-verifier"},
              {"type": "turn.started", "turn_id": "exact-artifact-check"},
              {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}},
              {"type": "turn.completed", "turn_id": "exact-artifact-check", "usage": {"input_tokens": 0, "output_tokens": 0}}]
    for event in events:
        print(json.dumps(event), flush=True)


if __name__ == "__main__":
    main()
