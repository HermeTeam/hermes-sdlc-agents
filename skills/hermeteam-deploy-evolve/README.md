# HermeTeam Deploy & Evolve skill package

This package contains the repository-owned operator skill for interactive local deployment of `HermeTeam/hermes-sdlc-agents`, recovery branching, evidence capture, and reviewed self-evolution.

Files:

- `SKILL.md` — executable deployment/evolution procedure;
- `templates/deploy-session.yaml` — sanitized deployment state;
- `templates/branch-decision.yaml` — recovery branch record;
- `templates/evolution-proposal.yaml` — reviewed skill-evolution proposal.

This is primarily an **operator/deployment skill**. Normal SDLC roles still obey their narrower `SOUL.md`, tool allowlist, approvals, and provider authority.

The active version is immutable during a deployment session. Evidence may produce a candidate child or specialized fork, but candidates remain `PROPOSED_FOR_HUMAN_REVIEW` until explicitly reviewed and promoted.

Repository-wide merge rules in `/AGENTS.md` require every functional PR targeting `master` to assess whether this skill must change and to update it in the same PR when deployment-visible behavior changes.
