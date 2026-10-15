# Vol.20 local account recovery — build101.21

Status: implemented; packaged validation and Owner password entry remain separate gates.

The101.20 Owner login reported `INVALID_CREDENTIALS`. Read-only evidence showed
the correct original installation, an active account, unchanged preupgrade
credential records and `password_verification_failed`. The input mismatch cause
remains unknown. Do not describe it as a proven autofill or migration defect.
Owner authorized data-preserving credential recovery on2026-10-08.

## Visual flow / 可视化恢复

1. Finish active work; normally quit TWOS and reopen it. Select the original
   environment. **Before Open selected environment**, choose **Recover local
   account… / 恢复本地账号…**. A running service cannot be silently stopped here.
2. Read the selected-environment scope. Choose **Verify macOS identity /
   验证 macOS 本机身份**, then personally complete Apple's system authentication.
   The macOS password is not supplied to TWOS or the assistant.
3. Verify the displayed existing username, account ID and installation identity.
   Enter **New local password / 新的本地密码** and **Confirm new local password /
   确认新的本地密码**,8–200 characters. Credentials are entered personally, never
   in chat, a command argument, browser storage or diagnostic log.
4. Choose **Review password change / 审查密码更改**, inspect the scope again, then
   **Reset this account password / 重设此账号密码**. Cancel leaves the password
   unchanged. A consistent private database snapshot must be saved first.
5. Wait for **Account password recovered / 本地账号密码已恢复**. Open the selected
   environment and sign in with the new password. Verify existing projects and
   delivery history; do not repeat old Run, Apply, Commit or Push.

No account is created, activated or merged. Only the existing active account's
password is updated, prior sessions revoked and an audit event appended. User ID and business
records remain. A snapshot contains sensitive account state: keep it private and
do not publish or casually restore it over newer data. Completion is recorded in
the atomic `owner_recovered` transaction; a snapshot receipt alone is not proof
that a password changed.

## Boundaries

- No HTTP reset route, provider/model call, arbitrary database path, SQL repair,
  downloaded helper, migration, restore or automatic retry.
- Native macOS user presence is required; no verification bypass for engineering.
  The local OS account already owns the database, as in the existing maintenance
  CLI. This is not remote account recovery.
- The startup lock plus exclusive cross-process maintenance lease exclude running
  TWOS connections. Unresolved execution/staging is rejected by the existing
  maintenance safety checks. Symlinks, hardlinked files, public storage, missing
  installation and unsupported schemas fail closed.
- Exact account/installation plus per-process nonce bind confirmation. The frame
  is bounded to8192bytes and300seconds, including partial input. Cancellation/EOF
  and timeout do not change credentials. A durable snapshot precedes the single
  transaction. Error output includes fixed codes only.
- Existing one-time `owner_recovered` policy is preserved. A completed recovery
  cannot be repeated. Failure/cancellation before a transaction can be explicitly
  retried. An uncertain result must be inspected, not blindly retried.
- No automatic login or approval. Engineering reset tests use synthetic accounts;
  only the Owner may enter/reset the real credential and accept the product.

## Validation criteria

Synthetic tests must prove old password rejected/new password accepted after
restart, old session invalid, account ID and every non-auth/audit table unchanged,
backup matching the prior database, cancellation/input errors/locks/storage
failures nonmutating, cross-installation rejection, no secrets in protocol output
and one-shot repeat protection. Actual packaged GUI evidence must separately
identify native OS-auth/credential-entry boundaries, rather than claiming API
tests prove personal Owner reset. Full primary-path regression retains all prior
cases; prior101.20 test counts do not certify new runtime inputs.

Publication, trading, clinical permissions and final GA acceptance remain absent.

## 2026-10-08 native form follow-up — build101.22

Owner observed build101.21 password fields collapsed to narrow strips. Its empty
secure fields were arranged without width constraints. Separately, the synchronous
alert ran inside the main dispatch callback: after the worker's bounded timeout,
terminal handling waited behind the open modal. These are product defects, not
incorrect Owner input. The failed101.21 native evidence remains FAIL; it must not
be replaced by its successful backend protocol tests.

Build101.22 uses an explicit420-point accessory width and30-point secure fields,
with keyboard order and accessible placeholders. Nonblocking window sheets allow
worker timeout/error/exit handling to close an expired prompt immediately. The
controller drains stdout through EOF and observes process exit before declaring a
missing final receipt, and rechecks worker/lifecycle state before each confirmation.
There is no authentication bypass, credential autofill or automatic retry.

Actual AppKit geometry/lifecycle tests supplement backend tests. Personal system
verification, new credential entry, separate confirmation and subsequent login
remain a distinct native GUI gate; never infer them from source text or an API test.
