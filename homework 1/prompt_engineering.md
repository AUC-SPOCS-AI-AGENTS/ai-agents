### Prompt Engineering Concepts

Use this file to explain 3 different prompt engineering concepts that you tried and their effectiveness. You can include screenshots of your prompts and the AI's responses if you like.
### Prompt Engineering Concepts

#### 1. Few-shot examples
The Orchestrator's example had no quotes so the AI wrote `role=Content Expert` instead of `role="Content Expert"`, and the app crashed.
 I fix the example and added one example for each expert.
 Worked.

#### 2. (constraints)
 The Read Expert searched with `name = 'INARA'`, but the database has `INARA Organization | Gaza`, so it found nothing.
 I told it to use `LIKE '%keyword%'` instead of `=`.
 Worked. It now finds the right dates.

#### 3.  (negative constraints)
 The AI added an extra filter `city LIKE '%Gaza%'` (city is empty), and once returned an empty plan `[]`.
 I added rules like "Never filter on city" and "Never return an empty list".
 Mostly worked. The AI is not 100% consistent, so it can still make mistakes sometimes.