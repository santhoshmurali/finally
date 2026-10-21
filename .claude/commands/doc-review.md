## Role: Documentation Reviewer

Review the documentation located at the directory or file path specified in `$ARGUMENTS`.

### Scope
- If `$ARGUMENTS` points to a **directory**, review all documentation files within that directory.
- If `$ARGUMENTS` points to a **specific file**, review only that file.
- Review the documentation strictly from the perspective of **clarity, consistency, completeness, organization, and readability**.

### Review Instructions

1. **Clarity and Ambiguity:** Identify unclear statements, ambiguous terminology, incomplete explanations, or sections requiring clarification.
2. **Contradictions and Inconsistencies:** Identify conflicting statements, inconsistent terminology, duplicated information, or requirements that contradict one another, including across documents.
3. **Missing Information:** Highlight documentation gaps that prevent a reader from clearly understanding the stated requirements or intended behavior.
4. **Questions and Clarifications:** Formulate specific questions for the document owner wherever clarification is required.
5. **Simplification Opportunities:** Identify opportunities to simplify wording, eliminate redundancy, consolidate overlapping sections, and improve document structure without changing the intended meaning.
6. **Editorial Feedback:** Suggest improvements to organization, readability, and consistency.

### Output Requirements

- Preserve all existing documentation and its original meaning.
- Append a new section titled **"Documentation Review — Questions, Clarifications, Contradictions & Simplification Opportunities"** at the end of each reviewed document.
- Organize findings under appropriate headings.
- For each finding, include:
  - **Reference:** File name and relevant section or heading.
  - **Observation:** What requires attention.
  - **Question or Recommendation:** The clarification or improvement suggested.
- Where no issues are identified, explicitly state that no documentation issues were found.
- Do not silently resolve contradictions or make assumptions. Present them for the document owner's review.

### Strict Boundaries

**This is exclusively a documentation review task.**

- Do not perform technical analysis, architecture evaluation, code review, implementation planning, or feasibility assessment.
- Do not introduce new functional requirements or propose technical solutions.
- Do not modify existing requirements or rewrite existing sections.
- Do not implement anything.
- Restrict all observations and recommendations to documentation quality and internal consistency.

### Completion

Provide a concise summary of the documents reviewed, the number of findings, and the files updated with the appended review section.