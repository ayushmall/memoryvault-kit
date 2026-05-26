# Skill evolution — controlled, version-tracked, user-approved

The kit ships skills as read-only files. Users can edit them by hand at
`<plugin>/skills/<name>/SKILL.md` — that's git-tracked, easy to roll
back, and the natural way to fork behavior. But there's a stronger ask:

> Can /memory-refresh learn from my inputs/errors and propose edits to
> the skill files themselves, so my skills get more "me" over time?

The answer here is: **yes, but with strong guardrails**. The reasoning
and the design follow.

## Why not just let skills self-edit at runtime

Five reasons we don't:

1. **Trust boundary.** The skill is also a prompt. A runtime self-edit
   means an LLM is rewriting its own instructions. That's a class of
   change you can't safely scale.
2. **Divergence from upstream.** If your local skill drifts silently,
   `git pull` of the kit becomes a merge nightmare.
3. **Hard to roll back.** A skill that edited itself yesterday has no
   commit; you can't `git checkout HEAD~1 -- skills/`.
4. **Data leakage.** A self-modifying skill that absorbs raw chat
   transcripts will eventually paste sensitive content into its own
   description.
5. **Auditability.** If something breaks, you should be able to point
   at a commit. Self-edits don't leave one.

## What we ship instead — three concentric layers

### Layer 1 — `learned_preferences.json` (already shipped)

Vault-local config the user owns. Skills READ it at start; skills NEVER
write to it directly. `/memory-refresh` is the only thing that proposes
additions, and only with explicit user confirmation. See
[`.mvkit/learned_preferences.example.json`](../.mvkit/learned_preferences.example.json).

Use cases this handles:
- "stop ingesting #random" → `source_overrides.slack.skip_channels_extra`
- "always skip dependabot PRs" → `source_overrides.github_prs.skip_authors`
- "stop showing me items mentioning `<legal_phrase>`" → `filter_rules.always_skip_titles_matching`

This is enough for ~80% of the "make it more me" ask.

### Layer 2 — proposed skill patches (this design, not yet built)

When /memory-refresh sees a pattern that can't be expressed as a
config tweak (e.g. "this skill keeps missing X because its dispatch
order is wrong"), it can **propose a patch**, not apply one.

Mechanic:

1. /memory-refresh writes the proposed change to
   `skills/<name>/.proposed.patch` — a unified diff against the current
   SKILL.md.
2. Surfaces it in the refresh report:
   ```
   Proposed skill edit: memory-master-ingest
   Rationale: 3 runs in a row, Linear sub-agent crashed because it
              tried to pull deltas before reading connected_sources.json.
              Suggested fix: reorder Steps 1 and 2 in the SKILL.md.
   To review: cat skills/memory-master-ingest/.proposed.patch
   To apply: cd ~/memoryvault-kit && git apply skills/memory-master-ingest/.proposed.patch && git add -A && git commit -m "apply proposed skill edit"
   To reject: rm skills/memory-master-ingest/.proposed.patch
   ```
3. Nothing happens until the user runs `git apply`. The diff lives as a
   file the user reviews like a PR.
4. Once applied, it's a normal git commit. Rollback is `git revert`.

This gives the user a forking mechanism that the kit itself proposes,
without ever letting an LLM mutate prompts at runtime.

### Layer 3 — fork-and-customize (always available)

Power users who don't want the proposal-flow at all just:

```bash
cd ~/memoryvault-kit
git checkout -b my-skills
# hack skills/<name>/SKILL.md
```

Their fork stays git-tracked. `git pull upstream` from the kit shows
conflicts they can resolve. Same model as any other dotfile fork.

## What stays OUT of scope

- **Auto-applied skill edits.** No matter how confident the
  proposal-engine is, the user clicks apply.
- **Self-edits during the run.** A skill can't rewrite itself
  mid-execution. It can write to `.proposed.patch`, that's it.
- **Description-field edits.** The `description:` in frontmatter is
  what Claude Code uses for tool dispatch — wrong description means
  wrong skill fires. Patches that touch `description:` get a louder
  warning.
- **Plugin-config edits.** `.claude-plugin/plugin.json` is install-time
  config, not a skill, and is excluded from proposed-patch generation.

## Implementation sketch (Layer 2)

Roughly 100 lines of Python + a small addition to /memory-refresh.

```python
# memoryvault_kit/skill_evolution.py
def propose_skill_patch(skill_name: str, rationale: str, diff: str):
    """Write a .proposed.patch + audit memory. Never applies."""
    skill_dir = KIT_ROOT / "skills" / skill_name
    if not skill_dir.is_dir():
        raise ValueError(f"unknown skill: {skill_name}")
    patch_path = skill_dir / ".proposed.patch"
    patch_path.write_text(diff)
    # Also write an audit memory so the user sees it in their refresh report
    _write_audit_memory(
        title=f"Proposed skill edit: {skill_name}",
        body=f"{rationale}\n\nDiff:\n```\n{diff[:2000]}\n```\n\n"
             f"Apply: git apply skills/{skill_name}/.proposed.patch\n"
             f"Reject: rm skills/{skill_name}/.proposed.patch",
        tags=["skill-evolution", "proposed", skill_name],
    )
```

And in `/memory-refresh`'s final report:

```
## Proposed skill edits this run
- memory-master-ingest: reorder Steps 1 and 2 — see .proposed.patch
- memory-refresh: add a Step 4d for proposal cleanup — see .proposed.patch
```

User reviews `git diff` on the .patch file, applies what they want.

## Why this is "controlled" not "free"

The skill files stay first-class git artifacts. The "evolution" is just
a structured suggestion channel from `/memory-refresh` to the user. It
preserves:

- **Reversibility**: every change is a commit, git revert undoes it
- **Auditability**: the diff is the spec, the commit is the trail
- **Convergence**: upstream `git pull` keeps working because the kit
  doesn't blindly merge runtime mutations
- **User authority**: nothing happens without `git apply`

The downside: friction. The user has to actually run `git apply`. We
think that's right — for prompt edits, you want friction.
