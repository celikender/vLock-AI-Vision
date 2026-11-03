# Skills

A skill is a scenario package that tells Muse Spark how SAM 3.1 handles a scenario on
this site, and can add an optional Muse frame check (VLM) where SAM alone is limited.
Add or edit skills without code; the app reads this folder on every request.

```
skills/<id>/skill.json     scenario: keywords, rule template, optional VLM check
skills/<id>/knowledge.md   plant notes: object words that work on these cameras, timing, limits
skills/_site/knowledge.md  notes for every request (optional)
```

## skill.json

| Field | Meaning |
|---|---|
| `id` | Same as the folder name: lowercase letters, digits and hyphens. |
| `name`, `summary` | Shown in the app and to Muse. |
| `status` | `ready` (SAM only, tested) or `experimental` (uses or needs a VLM check). |
| `keywords` | Words that make Muse see this skill for a request (keyword lookup, no vector database). |
| `rule` | Optional rule template using the runtime's own fields: `target`, `secondTarget`, `firstRelation`, `secondRelation`, `join`, `persistence`, `outputType`, `output`. Values must be ones the app accepts. |
| `vlm` | Optional frame check: `mode` (`confirm`, `scene`, `classify`), `trigger` (`on_active` or `periodic`), `question`, `answers` (2-6 short answers, include `unsure`), `interval_seconds` (20-3600). |

## How it runs

1. **Configure:** the request is matched against skill keywords, names, summaries and
   notes. The best three skills and the site notes go to Muse as reference data,
   never as instructions. Muse proposes a rule as before and names the skill it used.
   The app still validates every field.
2. **Monitor:** SAM 3.1 decides Active / Clear / Unknown exactly as before.
3. **Frame check (optional, per zone):** only if the zone's skill has a `vlm` block and
   the operator ticked *Allow Muse frame checks* (frames go to Meta). `on_active`
   checks when SAM turns the zone Active, then every interval while it stays Active;
   `periodic` checks every interval. The answer goes to the zone tags `VlmState`,
   `VlmReason` and `VlmCheckedAt`. It is advisory: it never changes `Active` or
   `State`, and SCADA decides how to use it.

Invalid skills are skipped and listed in the app; they never stop it.
