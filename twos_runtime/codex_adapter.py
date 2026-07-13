from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import AuditEvent, CodexRun, Task, utc_now
from .self_hosting import create_owner_acceptance, git_source_state, run_git


@dataclass(frozen=True)
class CodexDetection:
    status: str
    found: bool
    executable: str | None
    version: str | None
    supported_command: str | None
    reason: str
    next_action: str

    def as_dict(self, include_path: bool = False) -> dict[str, object]:
        output = asdict(self)
        if not include_path:
            output.pop("executable", None)
        return output


class CodexAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def detect(self) -> CodexDetection:
        executable = self.settings.codex_executable or shutil.which("codex")
        if not executable or not Path(executable).is_file():
            return CodexDetection(
                status="unconfigured",
                found=False,
                executable=None,
                version=None,
                supported_command=None,
                reason="Codex CLI was not found on PATH.",
                next_action="Install and authenticate the supported Codex CLI, then refresh Runtime Status.",
            )
        try:
            version_result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            help_result = subprocess.run(
                [executable, "exec", "--help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CodexDetection(
                status="needs_setup",
                found=True,
                executable=executable,
                version=None,
                supported_command=None,
                reason=f"Codex entrypoint exists but could not run ({type(exc).__name__}).",
                next_action="Repair or reinstall the local Codex CLI binary and verify authentication.",
            )

        version_text = (version_result.stdout or version_result.stderr).strip().splitlines()
        version = version_text[0][:240] if version_result.returncode == 0 and version_text else None
        help_text = (help_result.stdout or help_result.stderr).strip()
        if version_result.returncode != 0 or help_result.returncode != 0:
            failed_checks = []
            if version_result.returncode != 0:
                failed_checks.append("version")
            if help_result.returncode != 0:
                failed_checks.append("non-interactive exec")
            reason = f"Codex CLI {' and '.join(failed_checks)} capability check failed."
            return CodexDetection(
                status="needs_setup",
                found=True,
                executable=executable,
                version=version,
                supported_command=None,
                reason=reason[:1000],
                next_action="Repair Codex CLI setup or authentication, then run detection again.",
            )
        if "exec" not in help_text.lower():
            return CodexDetection(
                status="needs_setup",
                found=True,
                executable=executable,
                version=version,
                supported_command=None,
                reason="Installed Codex CLI does not advertise the required non-interactive exec command.",
                next_action="Upgrade to a Codex CLI version that supports codex exec.",
            )
        return CodexDetection(
            status="configured",
            found=True,
            executable=executable,
            version=version,
            supported_command="exec",
            reason="Codex CLI and non-interactive exec command were detected.",
            next_action="Approve the current Codex Instruction Pack before running it.",
        )

    def source_state(self) -> dict[str, object]:
        return git_source_state(self.settings.source_repo)

    def create_worktree(self, run_id: int, source_commit: str) -> tuple[Path, str]:
        state = self.source_state()
        if not state["clean"]:
            raise RuntimeError("Source repository must be clean before creating an isolated Codex run.")
        if state["commit"] != source_commit:
            raise RuntimeError("Source repository HEAD differs from the approved instruction-pack baseline.")
        token = uuid.uuid4().hex[:8]
        branch = f"twos/codex-run-{run_id}-{token}"
        root = self.settings.worktree_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        worktree = root / f"run-{run_id}-{token}"
        run_git(Path(state["repo"]), "worktree", "add", "-b", branch, str(worktree), source_commit, timeout=60)
        return worktree, branch

    def command_for(self, detection: CodexDetection, pack_content: str) -> list[str]:
        if detection.status != "configured" or not detection.executable or not detection.supported_command:
            raise RuntimeError("Codex CLI is not configured for execution.")
        return [detection.executable, detection.supported_command, pack_content]


class CodexExecutionManager:
    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings
        self.adapter = CodexAdapter(settings)
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[str]] = {}
        self._cancel_requested: set[int] = set()

    def recover_interrupted_runs(self) -> None:
        with self.factory() as session:
            runs = session.query(CodexRun).filter(CodexRun.status.in_(["queued", "running"])).all()
            for run in runs:
                run.status = "needs_review"
                run.owner_summary = "Server restarted while the Codex process was active; process state requires review."
                run.finished_at = utc_now()
                run.task.status = "needs_review"
                session.add(
                    AuditEvent(
                        action="codex_run_recovered",
                        entity_type="codex_run",
                        entity_id=run.id,
                        details="Interrupted process marked needs_review after restart.",
                    )
                )
            session.commit()

    def start(self, run_id: int) -> None:
        thread = threading.Thread(target=self._execute, args=(run_id,), daemon=True, name=f"twos-codex-{run_id}")
        thread.start()

    def cancel(self, run_id: int) -> bool:
        with self._lock:
            self._cancel_requested.add(run_id)
            process = self._processes.get(run_id)
        if process and process.poll() is None:
            process.terminate()
            return True
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if not run or run.status not in {"queued", "running"}:
                return False
            run.status = "cancelled"
            run.cancelled = True
            run.finished_at = utc_now()
            run.task.status = "cancelled"
            session.add(
                AuditEvent(
                    action="codex_run_cancelled",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details="Owner cancelled Codex execution.",
                )
            )
            session.commit()
        return True

    def _execute(self, run_id: int) -> None:
        started_monotonic = time.monotonic()
        detection = self.adapter.detect()
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if not run:
                return
            if run.status == "cancelled" or self._is_cancel_requested(run_id):
                self._finish_cancelled(session, run)
                return
            run.executable_status = detection.status
            if detection.status != "configured":
                run.status = "failed"
                run.owner_summary = detection.reason
                run.stderr = detection.reason
                run.finished_at = utc_now()
                run.task.status = "failed"
                session.add(
                    AuditEvent(
                        action="codex_run_failed",
                        entity_type="codex_run",
                        entity_id=run.id,
                        details="Codex CLI detection failed before execution.",
                    )
                )
                session.commit()
                return
            try:
                worktree, branch = self.adapter.create_worktree(run.id, run.source_commit)
            except Exception as exc:
                run.status = "failed"
                run.owner_summary = str(exc)
                run.stderr = str(exc)
                run.finished_at = utc_now()
                run.task.status = "failed"
                session.add(
                    AuditEvent(
                        action="codex_run_failed",
                        entity_type="codex_run",
                        entity_id=run.id,
                        details="Isolated worktree creation failed.",
                    )
                )
                session.commit()
                return
            run.worktree_path = str(worktree)
            run.worktree_branch = branch
            run.status = "running"
            run.started_at = utc_now()
            run.task.status = "running"
            pack_content = run.pack.content
            session.add(
                AuditEvent(
                    action="codex_run_started",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=f"Isolated branch {branch} started.",
                )
            )
            session.commit()

        command = self.adapter.command_for(detection, pack_content)
        stdout = ""
        stderr = ""
        exit_code: int | None = None
        timed_out = False
        cancelled = False
        try:
            process = subprocess.Popen(
                command,
                cwd=worktree,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with self._lock:
                self._processes[run_id] = process
            try:
                stdout, stderr = process.communicate(timeout=self.settings.codex_timeout_seconds)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                stdout, stderr = process.communicate()
                exit_code = process.returncode
            cancelled = self._is_cancel_requested(run_id)
        except OSError as exc:
            stderr = str(exc)
            exit_code = -1
        finally:
            with self._lock:
                self._processes.pop(run_id, None)

        result = self._derive_result(worktree, run_id, stdout, stderr, exit_code, timed_out, cancelled)
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if not run:
                return
            run.stdout, stdout_truncated = self._truncate(stdout)
            run.stderr, stderr_truncated = self._truncate(stderr)
            run.output_truncated = stdout_truncated or stderr_truncated
            run.exit_code = exit_code
            run.duration_ms = duration_ms
            run.timed_out = timed_out
            run.cancelled = cancelled
            run.structured_result = json.dumps(result, separators=(",", ":"))
            run.finished_at = utc_now()
            if cancelled:
                run.status = "cancelled"
                run.owner_summary = "Codex execution was cancelled by the Owner."
                run.task.status = "cancelled"
            elif timed_out:
                run.status = "timed_out"
                run.owner_summary = "Codex execution exceeded the configured timeout."
                run.task.status = "needs_review"
            elif exit_code != 0:
                run.status = "failed"
                run.owner_summary = "Codex process failed; inspect Result and Advanced raw output."
                run.task.status = "needs_review"
            elif not result["validation"]["diff_check"] or not result["changed_files"]:
                run.status = "needs_review"
                run.owner_summary = "Codex exited successfully, but Git evidence requires Owner review."
                run.task.status = "needs_review"
            else:
                run.status = "completed"
                run.owner_summary = "Codex completed in an isolated worktree; Git-derived result is ready."
                run.task.status = "result_ready"
            create_owner_acceptance(session, run.task, run)
            if run.status not in {"completed", "needs_review"}:
                run.task.status = "needs_review" if run.status in {"failed", "timed_out"} else run.status
            session.add(
                AuditEvent(
                    action="codex_run_completed",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=f"status={run.status}; exit_code={run.exit_code}; changed_files={len(result['changed_files'])}",
                )
            )
            session.commit()

    def _derive_result(
        self,
        worktree: Path,
        run_id: int,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        timed_out: bool,
        cancelled: bool,
    ) -> dict[str, object]:
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            source_commit = run.source_commit if run else ""
            source_branch = run.source_branch if run else ""
        post_commit = run_git(worktree, "rev-parse", "HEAD", check=False).stdout.strip()
        branch = run_git(worktree, "branch", "--show-current", check=False).stdout.strip()
        status_text = run_git(worktree, "status", "--porcelain", "--untracked-files=all", check=False).stdout.strip()
        committed_files = run_git(worktree, "diff", "--name-only", f"{source_commit}..HEAD", check=False).stdout.splitlines()
        status_files = [line[3:] for line in status_text.splitlines() if len(line) > 3]
        changed_files = sorted({item for item in [*committed_files, *status_files] if item})
        committed_stat = run_git(worktree, "diff", "--stat", f"{source_commit}..HEAD", check=False).stdout.strip()
        working_stat = run_git(worktree, "diff", "--stat", check=False).stdout.strip()
        cached_stat = run_git(worktree, "diff", "--cached", "--stat", check=False).stdout.strip()
        commits = run_git(
            worktree,
            "log",
            "--format=%H%x09%s",
            f"{source_commit}..HEAD",
            check=False,
        ).stdout.splitlines()
        checks = [
            run_git(worktree, "diff", "--check", f"{source_commit}..HEAD", check=False),
            run_git(worktree, "diff", "--check", check=False),
            run_git(worktree, "diff", "--cached", "--check", check=False),
        ]
        diff_check = all(item.returncode == 0 for item in checks)
        test_lines = [
            line.strip()
            for line in stdout.splitlines()
            if any(token in line.lower() for token in [" passed", " failed", "pytest", "test result"])
        ][:20]
        return {
            "pre_run_commit": source_commit,
            "post_run_commit": post_commit,
            "source_branch": source_branch,
            "worktree_branch": branch,
            "working_tree_status": status_text or "clean",
            "changed_files": changed_files,
            "diff_summary": "\n".join(part for part in [committed_stat, working_stat, cached_stat] if part),
            "commits": commits,
            "process": {
                "exit_code": exit_code,
                "timed_out": timed_out,
                "cancelled": cancelled,
                "stderr_present": bool(stderr),
            },
            "validation": {"diff_check": diff_check},
            "tests_reported": test_lines,
            "boundary_confirmation": {
                "isolated_worktree": True,
                "automatic_merge": False,
                "automatic_push": False,
            },
        }

    def _truncate(self, value: str) -> tuple[str, bool]:
        if len(value) <= self.settings.codex_output_limit:
            return value, False
        suffix = "\n[output truncated by TWOS]"
        return value[: self.settings.codex_output_limit - len(suffix)] + suffix, True

    def _is_cancel_requested(self, run_id: int) -> bool:
        with self._lock:
            return run_id in self._cancel_requested

    def _finish_cancelled(self, session: Session, run: CodexRun) -> None:
        run.status = "cancelled"
        run.cancelled = True
        run.finished_at = utc_now()
        run.task.status = "cancelled"
        session.add(
            AuditEvent(
                action="codex_run_cancelled",
                entity_type="codex_run",
                entity_id=run.id,
                details="Owner cancelled Codex execution before process start.",
            )
        )
        session.commit()
