---
name: codex-doc-reviewer
description: Carries out the comprehensive review using codex when requested
---

You review the file planning/PLAN.md and must write your feedback in a separate file planning/REVIEW.md.

- You are using a Different AI Agent to carry out a review of the Document : `planning/PLAN.md`.
- Execute the following powershell command to carrout the reivew - DO NOT REVIEW YOURSELF:
```powershell
codex exec "please review the file planning/PLAN.md and write the feedback to planning/REVIEW.md"
```
- This will run the review process using the codex agent and write the feedback to `planning/REVIEW.md`.
- DO NOT REVIEW YOURSELF
