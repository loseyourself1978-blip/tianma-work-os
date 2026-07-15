from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import AuditEvent, CodexRun, Task, utc_now
from .self_hosting import create_owner_acceptance, git_source_state, run_git


OUTPUT_TRUNCATION_SUFFIX = "\n[output truncated by TWOS]"
CHILD_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "CODEX_HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "USER",
    "LOGNAME",
    "SHELL",
    "TERM",
)


class _SharedOutputBudget:
    """Drain both process streams while retaining a bounded combined payload."""

    def __init__(self, limit: int) -> None:
        self.remaining = max(0, limit)
        self._lock = threading.Lock()

    def retain(self, chunk: bytes) -> tuple[bytes, bool]:
        with self._lock:
            retained = chunk[: self.remaining]
            self.remaining -= len(retained)
        return retained, len(retained) != len(chunk)


class _StreamCapture:
    def __init__(self, stream, budget: _SharedOutputBudget) -> None:
        self.stream = stream
        self.budget = budget
        self.chunks: list[bytes] = []
        self.truncated = False

    def drain(self) -> None:
        try:
            while True:
                chunk = self.stream.read(8192)
                if not chunk:
                    return
                retained, truncated = self.budget.retain(chunk)
                if retained:
                    self.chunks.append(retained)
                self.truncated = self.truncated or truncated
        finally:
            self.stream.close()

    def data(self) -> bytes:
        return b"".join(self.chunks)


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

    def discard_unstarted_worktree(self, worktree: Path, branch: str) -> None:
        source_repo = self.settings.source_repo.resolve()
        run_git(source_repo, "worktree", "remove", "--force", str(worktree), check=False, timeout=60)
        run_git(source_repo, "branch", "-D", branch, check=False, timeout=30)

    def command_for(self, detection: CodexDetection, pack_content: str) -> list[str]:
        if detection.status != "configured" or not detection.executable or not detection.supported_command:
            raise RuntimeError("Codex CLI is not configured for execution.")
        # The approved pack is transported through stdin using Codex's documented
        # `-` prompt sentinel. Keeping it out of argv avoids ARG_MAX failures and
        # guarantees that shell metacharacters remain inert data.
        return [
            detection.executable,
            detection.supported_command,
            "--sandbox",
            "workspace-write",
            "--ephemeral",
            "--ignore-user-config",
            "--color",
            "never",
            "-",
        ]


class CodexExecutionManager:
    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings
        self.adapter = CodexAdapter(settings)
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[bytes]] = {}
        self._workers: dict[int, threading.Thread] = {}
        self._cancel_requested: set[int] = set()
        self._stopping = False

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

    def start(self, run_id: int) -> bool:
        thread = threading.Thread(
            target=self._run_worker,
            args=(run_id,),
            daemon=True,
            name=f"twos-codex-{run_id}",
        )
        with self._lock:
            if self._stopping:
                return False
            self._workers[run_id] = thread
        thread.start()
        return True

    def _run_worker(self, run_id: int) -> None:
        try:
            self._execute(run_id)
        except Exception as exc:
            self._mark_worker_failure(run_id, type(exc).__name__)
        finally:
            with self._lock:
                self._workers.pop(run_id, None)

    def cancel(self, run_id: int) -> bool:
        with self._lock:
            self._cancel_requested.add(run_id)
            process = self._processes.get(run_id)
        if process and process.poll() is None:
            self._stop_process_tree(process, force=False)
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

    def shutdown(self) -> None:
        """Stop every active process tree before the runtime exits."""
        with self._lock:
            self._stopping = True
            processes = list(self._processes.values())
            workers = list(self._workers.values())
        for process in processes:
            if process.poll() is None:
                self._stop_process_tree(process, force=False)
        deadline = time.monotonic() + 2.0
        for process in processes:
            if process.poll() is not None:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                self._stop_process_tree(process, force=True)
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(timeout=max(0.0, deadline - time.monotonic()))

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
            session.refresh(run)
            if run.status == "cancelled" or self._is_cancel_requested(run_id):
                self.adapter.discard_unstarted_worktree(worktree, branch)
                self._finish_cancelled(session, run)
                return
            session.refresh(run.pack)
            if not self._pack_is_executable(run):
                self.adapter.discard_unstarted_worktree(worktree, branch)
                self._finish_pack_blocked(session, run)
                return
            run.worktree_path = str(worktree)
            run.worktree_branch = branch
            run.status = "running"
            run.started_at = utc_now()
            run.task.status = "running"
            session.add(
                AuditEvent(
                    action="codex_run_started",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=f"Isolated branch {branch} started.",
                )
            )
            session.commit()

        stdout = ""
        stderr = ""
        exit_code: int | None = None
        timed_out = False
        cancelled = False
        output_truncated = False
        process: subprocess.Popen[bytes] | None = None
        drain_threads: list[threading.Thread] = []
        stdout_capture: _StreamCapture | None = None
        stderr_capture: _StreamCapture | None = None
        try:
            # Serialize the final approval check with SQLite writers so a task
            # edit cannot invalidate the pack between this check and spawn.
            with self.factory() as launch_session:
                if launch_session.get_bind().dialect.name == "sqlite":
                    launch_session.execute(text("BEGIN IMMEDIATE"))
                launch_run = launch_session.get(CodexRun, run_id)
                if not launch_run:
                    return
                launch_session.refresh(launch_run.pack)
                if not self._pack_is_executable(launch_run):
                    self.adapter.discard_unstarted_worktree(worktree, branch)
                    launch_run.worktree_path = ""
                    launch_run.worktree_branch = ""
                    self._finish_pack_blocked(launch_session, launch_run)
                    return
                pack_content = launch_run.pack.content
                command = self.adapter.command_for(detection, pack_content)
                with self._lock:
                    if self._stopping or run_id in self._cancel_requested or launch_run.status == "cancelled":
                        self.adapter.discard_unstarted_worktree(worktree, branch)
                        launch_run.worktree_path = ""
                        launch_run.worktree_branch = ""
                        self._finish_cancelled(launch_session, launch_run)
                        return
                    process = subprocess.Popen(
                        command,
                        cwd=worktree,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=self._child_environment(),
                        start_new_session=os.name == "posix",
                    )
                    self._processes[run_id] = process
                launch_session.commit()

            budget = _SharedOutputBudget(self.settings.codex_output_limit)
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_capture = _StreamCapture(process.stdout, budget)
            stderr_capture = _StreamCapture(process.stderr, budget)
            for name, capture in (("stdout", stdout_capture), ("stderr", stderr_capture)):
                thread = threading.Thread(
                    target=capture.drain,
                    daemon=True,
                    name=f"twos-codex-{run_id}-{name}",
                )
                thread.start()
                drain_threads.append(thread)

            assert process.stdin is not None
            stdin_thread = threading.Thread(
                target=self._write_pack,
                args=(process, pack_content),
                daemon=True,
                name=f"twos-codex-{run_id}-stdin",
            )
            stdin_thread.start()
            drain_threads.append(stdin_thread)

            exit_code, timed_out, cancelled = self._wait_for_process(run_id, process)
        except OSError as exc:
            stderr = str(exc)
            exit_code = -1
        finally:
            if process and process.poll() is None:
                self._stop_process_tree(process, force=True)
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
            for thread in drain_threads:
                thread.join(timeout=2.0)
            if process and process.stdin and not process.stdin.closed:
                process.stdin.close()
            with self._lock:
                self._processes.pop(run_id, None)

        if stdout_capture and stderr_capture:
            stdout, stderr, output_truncated = self._bounded_outputs(stdout_capture, stderr_capture)

        result = self._derive_result(worktree, run_id, stdout, stderr, exit_code, timed_out, cancelled)
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if not run:
                return
            run.stdout = stdout
            run.stderr = stderr
            run.output_truncated = output_truncated
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
            elif not self._boundary_evidence_passes(result):
                run.status = "needs_review"
                run.owner_summary = "Codex exited successfully, but isolation or no-commit/no-push evidence requires review."
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
            source_repo = Path(run.source_repo) if run else worktree
        post_commit = run_git(worktree, "rev-parse", "HEAD", check=False).stdout.strip()
        branch = run_git(worktree, "branch", "--show-current", check=False).stdout.strip()
        status_text = run_git(worktree, "status", "--porcelain", "--untracked-files=all", check=False).stdout.strip()
        untracked_files = [line[3:] for line in status_text.splitlines() if line.startswith("?? ")]
        committed_files = run_git(worktree, "diff", "--name-only", f"{source_commit}..HEAD", check=False).stdout.splitlines()
        status_files = [line[3:] for line in status_text.splitlines() if len(line) > 3]
        changed_files = sorted({item for item in [*committed_files, *status_files] if item})
        committed_stat = run_git(worktree, "diff", "--stat", f"{source_commit}..HEAD", check=False).stdout.strip()
        working_stat = run_git(worktree, "diff", "--stat", check=False).stdout.strip()
        cached_stat = run_git(worktree, "diff", "--cached", "--stat", check=False).stdout.strip()
        untracked_stats: list[str] = []
        untracked_checks_ok = True
        worktree_root = worktree.resolve()
        for relative_path in untracked_files:
            candidate = (worktree / relative_path).resolve()
            if not candidate.is_relative_to(worktree_root) or not candidate.is_file():
                untracked_checks_ok = False
                continue
            check_result = run_git(
                worktree,
                "diff",
                "--no-index",
                "--check",
                "--",
                os.devnull,
                relative_path,
                check=False,
            )
            if check_result.returncode not in {0, 1} or check_result.stdout.strip() or check_result.stderr.strip():
                untracked_checks_ok = False
            stat_result = run_git(
                worktree,
                "diff",
                "--no-index",
                "--stat",
                "--",
                os.devnull,
                relative_path,
                check=False,
            )
            if stat_result.stdout.strip():
                untracked_stats.append(stat_result.stdout.strip())
        commits = run_git(
            worktree,
            "log",
            "--format=%H%x09%s",
            f"{source_commit}..HEAD",
            check=False,
        ).stdout.splitlines()
        merge_commits = run_git(
            worktree,
            "rev-list",
            "--merges",
            f"{source_commit}..HEAD",
            check=False,
        ).stdout.splitlines()
        source_post_commit = run_git(source_repo, "rev-parse", "HEAD", check=False).stdout.strip()
        source_status = run_git(
            source_repo,
            "status",
            "--porcelain",
            "--untracked-files=all",
            check=False,
        ).stdout.strip()
        source_remotes = run_git(source_repo, "remote", check=False).stdout.splitlines()
        worktree_common_raw = run_git(worktree, "rev-parse", "--git-common-dir", check=False).stdout.strip()
        source_common_raw = run_git(source_repo, "rev-parse", "--git-common-dir", check=False).stdout.strip()
        worktree_common = self._resolved_git_path(worktree, worktree_common_raw)
        source_common = self._resolved_git_path(source_repo, source_common_raw)
        isolated_worktree = (
            worktree.resolve() != source_repo.resolve()
            and worktree_common is not None
            and worktree_common == source_common
        )
        source_unchanged = source_post_commit == source_commit and not source_status
        checks = [
            run_git(worktree, "diff", "--check", f"{source_commit}..HEAD", check=False),
            run_git(worktree, "diff", "--check", check=False),
            run_git(worktree, "diff", "--cached", "--check", check=False),
        ]
        diff_check = all(item.returncode == 0 for item in checks) and untracked_checks_ok
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
            "diff_summary": "\n".join(
                part for part in [committed_stat, working_stat, cached_stat, *untracked_stats] if part
            ),
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
                "isolated_worktree": isolated_worktree,
                "source_main_unchanged": source_unchanged,
                "source_post_run_commit": source_post_commit,
                "source_post_run_status": source_status or "clean",
                "merge_commits_created": bool(merge_commits),
                "source_remote_count": len(source_remotes),
                "push_target_configured": bool(source_remotes),
                "automatic_merge": False,
                "automatic_push": False,
            },
        }

    def _truncate(self, value: str) -> tuple[str, bool]:
        limit = max(0, self.settings.codex_output_limit)
        raw = value.encode("utf-8")
        if len(raw) <= limit:
            return value, False
        suffix = OUTPUT_TRUNCATION_SUFFIX.encode("utf-8")
        if limit <= len(suffix):
            return suffix[:limit].decode("utf-8", errors="ignore"), True
        retained = raw[: limit - len(suffix)] + suffix
        return retained.decode("utf-8", errors="ignore"), True

    def _bounded_outputs(
        self,
        stdout_capture: _StreamCapture,
        stderr_capture: _StreamCapture,
    ) -> tuple[str, str, bool]:
        stdout_data = stdout_capture.data()
        stderr_data = stderr_capture.data()
        truncated = stdout_capture.truncated or stderr_capture.truncated
        if not truncated:
            return (
                stdout_data.decode("utf-8", errors="ignore"),
                stderr_data.decode("utf-8", errors="ignore"),
                False,
            )
        limit = max(0, self.settings.codex_output_limit)
        suffix = OUTPUT_TRUNCATION_SUFFIX.encode("utf-8")
        if limit <= len(suffix):
            marker = suffix[:limit].decode("utf-8", errors="ignore")
            return (marker, "", True) if stdout_capture.truncated else ("", marker, True)
        content_limit = limit - len(suffix)
        stdout_data = stdout_data[:content_limit]
        stderr_data = stderr_data[: max(0, content_limit - len(stdout_data))]
        if stdout_capture.truncated:
            stdout_data += suffix
        else:
            stderr_data += suffix
        return (
            stdout_data.decode("utf-8", errors="ignore"),
            stderr_data.decode("utf-8", errors="ignore"),
            True,
        )

    def _child_environment(self) -> dict[str, str]:
        env = {key: os.environ[key] for key in CHILD_ENV_ALLOWLIST if key in os.environ}
        env["NO_COLOR"] = "1"
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    @staticmethod
    def _write_pack(process: subprocess.Popen[bytes], pack_content: str) -> None:
        if not process.stdin:
            return
        try:
            process.stdin.write(pack_content.encode("utf-8"))
            process.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            # Exit status and bounded stderr remain the authoritative evidence.
            return

    def _wait_for_process(
        self,
        run_id: int,
        process: subprocess.Popen[bytes],
    ) -> tuple[int | None, bool, bool]:
        deadline = time.monotonic() + self.settings.codex_timeout_seconds
        while process.poll() is None:
            if self._is_cancel_requested(run_id):
                self._stop_process_tree(process, force=False)
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._stop_process_tree(process, force=True)
                    process.wait(timeout=2.0)
                return process.returncode, False, True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop_process_tree(process, force=True)
                process.wait(timeout=2.0)
                return process.returncode, True, False
            try:
                process.wait(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                continue
        return process.returncode, False, self._is_cancel_requested(run_id)

    @staticmethod
    def _stop_process_tree(process: subprocess.Popen[bytes], force: bool) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif force:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            return

    @staticmethod
    def _pack_is_executable(run: CodexRun) -> bool:
        pack = run.pack
        return bool(
            pack
            and run.pack_id == pack.id
            and pack.status == "approved"
            and pack.invalidated_at is None
            and pack.source_baseline_commit == run.source_commit
        )

    @staticmethod
    def _resolved_git_path(repo: Path, value: str) -> Path | None:
        if not value:
            return None
        path = Path(value)
        return (path if path.is_absolute() else repo / path).resolve()

    @staticmethod
    def _boundary_evidence_passes(result: dict[str, object]) -> bool:
        boundary = result.get("boundary_confirmation")
        commits = result.get("commits")
        if not isinstance(boundary, dict) or not isinstance(commits, list):
            return False
        return bool(
            boundary.get("isolated_worktree")
            and boundary.get("source_main_unchanged")
            and not boundary.get("merge_commits_created")
            and not boundary.get("push_target_configured")
            and not commits
        )

    def _is_cancel_requested(self, run_id: int) -> bool:
        with self._lock:
            return self._stopping or run_id in self._cancel_requested

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

    def _finish_pack_blocked(self, session: Session, run: CodexRun) -> None:
        run.status = "failed"
        run.finished_at = utc_now()
        run.owner_summary = "The approved Codex Pack changed or was invalidated before process start. Nothing ran."
        run.task.status = "needs_review"
        session.add(
            AuditEvent(
                action="codex_run_blocked",
                entity_type="codex_run",
                entity_id=run.id,
                details="Approved pack was no longer executable before process start.",
            )
        )
        session.commit()

    def _mark_worker_failure(self, run_id: int, failure_type: str) -> None:
        with self._lock:
            process = self._processes.pop(run_id, None)
        if process and process.poll() is None:
            self._stop_process_tree(process, force=True)
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
        try:
            with self.factory() as session:
                run = session.get(CodexRun, run_id)
                if not run or run.status not in {"queued", "running"}:
                    return
                run.status = "needs_review"
                run.finished_at = utc_now()
                run.owner_summary = "TWOS stopped the Codex process after an internal execution error. Review is required."
                run.task.status = "needs_review"
                session.add(
                    AuditEvent(
                        action="codex_run_internal_failure",
                        entity_type="codex_run",
                        entity_id=run.id,
                        details=f"failure_type={failure_type}",
                    )
                )
                session.commit()
        except Exception:
            # Do not let secondary persistence failures resurrect a child process.
            return
