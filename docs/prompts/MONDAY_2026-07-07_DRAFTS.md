# Monday sign-off drafts — brain placement, voice, honesty (2026-07-07)

**Status:** DRAFT ONLY — do not deploy until Iko sign-off. Code references are
design notes for the next build slice, not implemented.

Probe evidence backing these drafts: `docs/probes/2026-07-04.md` (slide 11
44% → `speaker_notes`; slide 5 caption → `content.caption` still `null`).

---

## (a) Design note — changed-fields diff on fix result

### Problem

After a fix turn the user sees `✅ Updated 1 slide(s)` (now optionally preceded by
parallel model text). They cannot tell **which fields** changed. The brain's later
chat turn may claim changes that landed in non-visible fields (`speaker_notes`) or
not in the requested field (`caption` vs bullets). Honest UX requires the system to
report only what the regen **confirmed** changed.

### Proposed shape

Add an optional **`changed_fields`** block per edited slide, computed in code by
diffing pre-regen vs post-regen `SlideContent` (same slide_id), not by model
assertion.

```python
class SlideFieldChange(BaseModel):
    """One field that differed after regen (code-computed, not model-claimed)."""

    model_config = ConfigDict(extra="forbid")

    field: str  # e.g. "caption", "bullets[0]", "speaker_notes"
    before_snippet: str | None = Field(default=None, max_length=200)
    after_snippet: str | None = Field(default=None, max_length=200)


class SlideRegenResult(BaseModel):
    # ... existing slide, findings, costs ...
    changed_fields: list[SlideFieldChange] = Field(default_factory=list, max_length=30)
```

### Where it threads

1. **`EditorialPass.regenerate_slide_content`** — after Sonnet returns the new
   slide, diff `old_slide.content` vs `new_slide.content` (structured walk:
   title, subtitle, body_text, bullets, caption, stats, table_*, speaker_notes,
   etc.). Append `changed_fields` to `SlideRegenResult`
   (`packages/core/models/presentation.py:611`).

2. **`PresentationOrchestrator.regenerate_slide`** — pass through unchanged; log
   `changed_fields` in `presentation_slide_regenerated` JSON payload
   (`presentation_orchestrator.py:~580`).

3. **`PresentationOrchestrator.apply_fixes_and_render`** — aggregate per-fix
   `changed_fields` into `FixAndRenderResult` (new optional
   `changes_by_slide_id: dict[str, list[SlideFieldChange]]` or extend existing
   `fixes: list[SlideRegenResult]` — **prefer the latter**, no duplicate store).

4. **`presentation_flow._dispatch_fix`** — when building the
   `function_response` payload (`_append_fix_result`, ~1080):
   - Extend `{delivered, slides_changed, roster}` with
     `changes: {slide_id: [{field, after_snippet}, ...]}` capped for token size.
   - Feed the same summary into `reply_text` material when the model did not emit
     parallel text (code-generated one-liner: *"Updated caption on slide 5"* only
     if `caption` appears in `changed_fields` — never claim a field absent from
     the diff).

5. **Brain driver / next turn** — brain reads `function_response.changes` in
   history; no prompt change required for the diff itself (code-grounded).

### Invariants untouched

- Diff is **read-only observation** after regen; does not alter `SlideSpec` or
  history append discipline.
- Empty `changed_fields` on a "successful" regen flags structural no-op (slide 11
  class) for logging/alerts — does not auto-fail delivery (separate policy).

---

## (b) Placement line — `BRAIN_TOOL_DESCRIPTIONS` (draft paragraph)

Insert after the existing preservation-scope block (~line 751 in
`brain_prompts.py`), before `BRAIN_FIX_ONLY_SYSTEM`:

```
**Name the target field when the user names one.** If the user asks for a caption,
stat, bullet, title change, or speaker note, the instruction must say which
SlideContent field to write (caption, bullets, stats, title, speaker_notes, etc.)
and treat that field as the only mutable surface unless the user explicitly asked
for a rewrite. "Add a caption" means set content.caption — not fold the text into
bullets or speaker_notes because the layout looks full. When the layout has no
room for the requested field, say so in your reply and ask whether to replace a
bullet or expand the layout — do not silently redirect the content to another
field.
```

---

## (c) Voice / honesty paragraphs — `BRAIN_IDENTITY` or orchestrator (draft)

### Substitute-and-announce (when user names a wrong but source-adjacent value)

```
When the user names a specific number, date, or quote that is close to but not
identical to the source, do not refuse and wait for them to retype. Use the
grounded value from the claims/chunks, call edit_slides with that value in the
instruction, and in the same turn tell them what you substituted and why ("your
source says 44%, not 40% — I used 44%"). Never apply the user's ungrounded figure
even if they insist in the same message; substitution is not compliance with
fabrication.
```

### Report only what the result confirms (pairs with changed-fields diff in code)

```
After edit_slides, report only what the function_response confirms changed. If
you claimed a stat was added but the result does not show that field changed, say
you attempted the edit and it did not land in the requested place — do not repeat
the claim. The roster and (when present) the changes list in the result are
authoritative over your memory of the instruction.
```

---

## Related shipped (not part of Monday prompt deploy)

- Fix-turn parallel model text → user message (`2ed7cb9`): extracts `result.text`
  on fix exit; does not synthesize placement or diff text.
- `presentation_slide_regenerated` log fix (`pending deploy`): JSON-in-message
  pattern for droplet forensics.
