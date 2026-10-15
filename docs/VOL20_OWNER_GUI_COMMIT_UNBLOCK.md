# TWOS-V20.1-OWNER-GUI-COMMIT-UNBLOCK-R1

## TWOS-V20.1-GUI-COMMIT-IDENTITY-01

Confirmed on the Owner product instance under acceptance, App 1.0.1 build 101.1,
source 65da341855691947bcfe28c7ea562a0c93042919. The managed workspace's initial
commit uses command-local synthetic attribution. Subsequent Commit readiness
requires explicit repository-local name and email. Inherited global attribution
does not satisfy this gate, and build 101.1 has no GUI entry to save it.

The scoped repair adds **Owner Commit → Set Commit identity → Save identity**.
The dialog identifies the exact Project, Task and authorized repository. Fields
start empty; the Owner supplies attribution. It changes only that repository's
user.name and user.email, atomically. It creates neither a commit nor approval.
An exact durable configuration transition receipt permits Commit to use the
existing passed Apply evidence without changing that history or repeating Run.
Old proposals and approvals become unusable after an identity change.

The local patch is App 1.0.1 **build 101.2**, retaining the installation and
database schema contract. Build 101.1 and its DMG remain intact. Public release,
signing and Owner acceptance are outside this patch handoff. Actual compatibility
and test results belong to the task evidence, not inherited release test counts.

After installing the patch and signing in to the existing Owner account:
select the same Project and Task → Owner Commit → Set Commit identity → enter
your name and email → Save identity → review remaining blockers → Review Commit
→ inspect files, author, parent and subject → Approve Commit → Confirm Local
Commit. The last three actions belong to the Owner. Do not repeat Run or Apply.
Push requires a separately verified destination and explicit authorization;
private LDD context must not be pushed to the TWOS public source repository.

## Deferred product requirements — no implementation in this patch

### TWOS-UX-20260926-01 — RECORDED_FOR_CONSOLIDATED_REDESIGN

In-step operations, visible action areas, correct scroll positioning, context
preservation on refresh/back, and correction of cramped/overlapping navigation.

### TWOS-UX-20260926-02 — RECORDED_FOR_CONSOLIDATED_REDESIGN

Retain the complete first setup and acceptance flow. Simplify everyday work to
“request a task → automatic processing → result or decision needed.” Preserve
internal state and audit without requiring clicks through every internal stage.

### TWOS-UX-20260926-03 — RECORDED_FOR_CONSOLIDATED_REDESIGN

Risk-based delegated review: system or independent AI may continue within an
explicit low-risk permission scope. High risk, out-of-scope action, exceeded
budget, failed validation, reviewer disagreement and uncertainty escalate to
a human. AI_APPROVED must never be recorded as OWNER_APPROVED. The executor
cannot expand authority by declaring its own work low risk.

These three items are temporarily tolerated, not permanently waived for the
nontechnical product. No approval authority changes in this patch. LDD
order_authority remains NONE and medical human gates remain unchanged.

### TWOS-UX-20260926-04 — PROPOSED (not Owner-approved)

Define completion endpoints by task type. Research/report work need not require
Commit/Push. Enable remote synchronization only when the task needs it and its
destination is explicit. This is a design suggestion, not approved behavior.
