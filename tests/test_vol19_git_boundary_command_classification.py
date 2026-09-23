from __future__ import annotations

import json

import pytest

from twos_runtime.codex_adapter import _CodexJsonlEvidenceCollector


def _prohibited_attempts(command: str) -> list[str]:
    collector = _CodexJsonlEvidenceCollector("fixture-approved-model")
    event = {
        "type": "item.completed",
        "item": {
            "id": "command-1",
            "type": "command_execution",
            "command": command,
            "exit_code": 0,
        },
    }
    collector.feed((json.dumps(event) + "\n").encode("utf-8"))
    collector.finish()
    return collector.prohibited_git_attempts


def test_read_only_remote_and_local_config_inspection_is_not_a_git_mutation() -> None:
    command = (
        "rg -n 'fixture' . && git ls-tree -r HEAD && git remote -v && "
        "git config --local --list"
    )

    assert _prohibited_attempts(command) == []


@pytest.mark.parametrize(
    ("command", "expected_code"),
    [
        ("git add fixture.txt", "GIT_ADD_ATTEMPTED"),
        ("git rm fixture.txt", "GIT_RM_ATTEMPTED"),
        ("git mv before.txt after.txt", "GIT_MV_ATTEMPTED"),
        ("git commit -m fixture", "GIT_COMMIT_ATTEMPTED"),
        ("git push origin main", "GIT_PUSH_ATTEMPTED"),
        ("git reset --hard HEAD", "GIT_RESET_ATTEMPTED"),
        ("git clean -fd", "GIT_CLEAN_ATTEMPTED"),
        ("git checkout -- fixture.txt", "GIT_CHECKOUT_ATTEMPTED"),
        ("git switch fixture", "GIT_SWITCH_ATTEMPTED"),
        ("git restore fixture.txt", "GIT_RESTORE_ATTEMPTED"),
        ("git rebase main", "GIT_REBASE_ATTEMPTED"),
        ("git merge main", "GIT_MERGE_ATTEMPTED"),
        ("git tag fixture", "GIT_TAG_ATTEMPTED"),
        ("git remote add origin https://invalid.example/repo", "GIT_REMOTE_ATTEMPTED"),
        ("git config --local user.name fixture", "GIT_CONFIG_ATTEMPTED"),
        ("git update-index --refresh", "GIT_UPDATE_INDEX_ATTEMPTED"),
        ("git write-tree", "GIT_WRITE_TREE_ATTEMPTED"),
        ("git commit-tree HEAD^{tree}", "GIT_COMMIT_TREE_ATTEMPTED"),
        ("git update-ref refs/heads/main HEAD", "GIT_UPDATE_REF_ATTEMPTED"),
    ],
)
def test_all_prohibited_git_operations_remain_detected(
    command: str,
    expected_code: str,
) -> None:
    assert _prohibited_attempts(command) == [expected_code]


def test_read_only_inspection_does_not_hide_later_mutating_git_commands() -> None:
    command = (
        "git remote -v && git config --local --list && "
        "git remote set-url origin https://invalid.example/repo && "
        "git config --local user.email fixture@example.invalid && git push origin main"
    )

    assert _prohibited_attempts(command) == [
        "GIT_REMOTE_ATTEMPTED",
        "GIT_CONFIG_ATTEMPTED",
        "GIT_PUSH_ATTEMPTED",
    ]


@pytest.mark.parametrize('command', [
    "git config --local --get user.name",
    "git config --local --get-all remote.origin.url",
    "git config --local --get-regexp 'twos|snapshot|source'",
    'git config --local --get-regexp "twos|snapshot|source"',
    "/bin/bash -lc \"ls -la\n cat .git\n git remote -v\n git config --local --get-regexp 'twos|snapshot|source'\"",
])
def test_ga_read_only_config_queries_are_not_mutations(command):
    assert _prohibited_attempts(command) == []


@pytest.mark.parametrize('suffix', [
    '--unset-all user.name',
    '--add user.name changed',
    '--replace-all user.name changed',
    '--remove-section user',
    '--rename-section user changed',
    '--edit',
])
def test_read_query_prefix_does_not_allow_additional_config_actions(suffix):
    assert _prohibited_attempts("git config --local --get-regexp 'user.*' " + suffix) == ['GIT_CONFIG_ATTEMPTED']


def test_read_query_does_not_hide_following_mutation_or_substitution():
    assert _prohibited_attempts("git config --local --get-regexp 'user.*'; git config --local user.name changed") == ['GIT_CONFIG_ATTEMPTED']
    assert 'GIT_PUSH_ATTEMPTED' in _prohibited_attempts('git config --local --get-regexp "$(git push origin main)"')
