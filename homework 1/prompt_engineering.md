# Prompt Engineering Concepts

## 1. Role Prompting (Expert Specialization)

I used role prompting to give each AI expert a specific identity and responsibility. For example, the Database Read Expert is instructed to generate SQL queries, the Database Write Expert generates Python code to update the database, and the Content Expert answers questions using the resume content.

**Effectiveness:**

This approach helped separate the responsibilities of the experts. For example, when I asked the Content Expert to summarize the education section, it correctly identified Arab Open University in Cairo and did not invent missing details such as a degree or graduation date. This showed that role-specific instructions helped keep the response focused.

## 2. Constrained Output Formatting

I used explicit output-format instructions to control what each expert generates. The Database Read Expert must return a valid SQLite SELECT query only. The Database Write Expert must return executable Python code, and the Orchestrator must return a Python list of expert calls in the required format.

**Effectiveness:**

These constraints are important because the application processes the generated responses programmatically. They help make the outputs more predictable and easier to execute. The application successfully loaded the four expert configurations and processed resume-content questions. However, I could not fully verify the database-writing workflow because my resume database does not contain any experience entries.

## 3. Few-Shot Prompting

I added examples to the `few_shot_examples` field in the `llm_roles.csv` file. These examples demonstrate how the experts should respond. For instance, the Database Read Expert has an example of generating a SQL query, the Database Write Expert has an example of adding a skill, and the Orchestrator has an example of creating an ordered plan involving multiple experts.

**Effectiveness:**

The examples provide concrete demonstrations of the expected response format and help guide the model toward the desired behaviour. They are especially useful when the model needs to generate structured SQL, Python code, or expert-call plans. I included these examples in the system, although I did not perform a controlled comparison with and without them to measure their individual effect.