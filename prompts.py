CASES_LISTING_PROMPT = """
Act as a developer. You will be provided with a set of conditional rules, similar to if-else statements or logical expressions that determine different outcomes. Your task is to analyze these rules and extract all distinct minimal combinations of variable states (these are the "cases") that are relevant to evaluating these conditions and reaching a specific outcome or branch.

The goal is to identify each unique scenario described by the combination of conditions.

You will receive the rules like this:
[USER WILL PROVIDE THE RULES HERE, FOR EXAMPLE:
if {(varA is Missing OR varB == true} -> outcome1
if {(varA is not Missing AND varB == false) && (varC = "pending" OR varC = "")} -> outcome2
if {(varA is not Missing AND varB == false) && varC is not Missing AND varC != "pending" AND varC != ""} -> outcome3
]

Please return a JSON array of objects. Each object should represent a unique case. The keys in the object should be the variable names, and the values should be their states for that specific case.

Follow these guidelines meticulously:

1.  **Identify Variables:** Automatically identify all unique variable names mentioned in the conditions (e.g., `varA`, `varB`, `varC` from the example above, but these will change based on the input).
2.  **Representing Variable States (General Rules):**
    *   **"is Missing" / "is Null" / "is Empty" (for data presence):** If a condition states a variable `VAR` is "Missing" (or similar phrasing indicating absence of data, not an empty string value), represent this as: `"VAR": "missing"`.
    *   **"is not Missing" / "Exists" / "is Present":** If a condition states `VAR` is "not Missing" (or similar), represent this using a plausible, generic, but illustrative example value for that variable. You should infer a sensible placeholder. For example:
        *   If `VAR` seems to be a general string: `"VAR": "example_string_value"`
        *   If `VAR` seems to be a date: `"VAR": "example_date_value"`
        *   If `VAR` seems to be a numerical ID: `"VAR": "example_id_123"`
        *   If no specific type is clear, use a generic placeholder like `"VAR": "present_value"` or `"VAR": "some_non_missing_value"`.
    *   **Boolean Conditions:** If a condition is `VAR == true` or `VAR == false` (or `VAR is true/false`, `is VAR`), use JSON booleans: `"VAR": true` or `"VAR": false`.
    *   **Equality to Specific Values:**
        *   If `VAR = "specific_string_literal"`, use: `"VAR": "specific_string_literal"`.
        *   If `VAR = ""` (empty string literal), use: `"VAR": ""`.
        *   If `VAR = number_literal`, use: `"VAR": number_literal`.
    *   **Inequality to Specific Values:** If `VAR != "specific_string_literal"`, this implies `VAR` has a value, and that value is not "specific_string_literal". Represent this with an example value that satisfies this, e.g., `"VAR": "another_value"`. Be mindful if other conditions also constrain this `VAR`.
3.  **Handling Logical Operators (`AND`, `OR`, `NOT`, grouping `()`/`{}`):**
    *   **`OR` Conditions (e.g., `ConditionA OR ConditionB`):**
        *   This typically means there are multiple distinct paths. Generate separate cases:
            *   One case where `ConditionA` is true.
            *   Another case where `ConditionB` is true.
        *   To ensure these cases are distinct, if `ConditionA` sets `varX` to `val1`, and `ConditionB` involves `varX` as well (or doesn't mention it but `ConditionA` does), the case for `ConditionB` should ideally assume `varX` is *not* `val1` (or is in a state that makes `ConditionA` false) if that's what makes `ConditionB` the sole reason for truth in that path.
        *   Example: For `(varA is Missing OR varB == true)`:
            *   Case 1: `{ "varA": "missing" }`
            *   Case 2: `{ "varA": "example_string_value", "varB": true }` (assuming `varA` is not missing for this path to be distinct).
    *   **`AND` Conditions (e.g., `ConditionA AND ConditionB`):**
        *   The case object must include variable states satisfying *both* `ConditionA` and `ConditionB` simultaneously.
    *   **Combined Logic & Grouping:** Respect the order of operations and grouping. Deconstruct complex conditions.
        *   Example: `(P1 AND P2) && (P3 OR P4)` should be expanded into two main scenarios:
            1.  `P1 AND P2 AND P3`
            2.  `P1 AND P2 AND P4`
4.  **Minimal and Distinct Cases:**
    *   Each JSON object should represent a unique scenario derived directly from the logic.
    *   Sometimes, a common set of prerequisite conditions (e.g., `varA is not Missing AND varB == false`) might appear as a distinct case if it's a logical checkpoint *before* further branching (e.g., based on `varC`). Your goal is to list all combinations of variable states that the input logic explicitly or implicitly distinguishes.
    *   Focus on capturing the specific conditions that lead to a distinct logical path or outcome.
5.  **Scope:** Only include variables and their states if they are explicitly part of a condition being analyzed for a particular case. Do not add variables that are not mentioned in the path to that case.
6.  **Output Format:** The final output must be a single JSON array containing these case objects.

Now, I will provide the rules. Please generate the JSON array of cases based on these instructions.
"""

METADATA_JSON_PROMPT = """You will be provided with a set of conditional rules that define specific behaviors or values based on certain conditions. Your task is to reformat these rules into a specific JSON structure.

I will provide you with:
1.  The core conditional logic (e.g., if-else statements or similar pseudo-code).
2.  Metadata values for `identifier`, `parameter.name`, `parameter.link`, `prompts.name`, and `prompts.link`.

Your goal is to produce a single JSON object matching the following structure:

{
  "identifier": "PROVIDED_IDENTIFIER_VALUE",
  "parameter": {
    "name": "PROVIDED_PARAMETER_NAME",
    "link": "PROVIDED_PARAMETER_LINK"
  },
  "prompts": {
    "name": "PROVIDED_PROMPTS_NAME",
    "link": "PROVIDED_PROMPTS_LINK_OR_NULL"
  },
  "conditionalLogic": [
    // This array will be populated based on the input rules
    {
      "condition": "STRING_REPRESENTATION_OF_THE_CONDITION",
      "codeBlock": "OPTIONAL_COMMENT_OR_EXPLANATION_STRING", // Omit or null if not present
      "value": "STRING_OR_STRUCTURED_VALUE_FOR_THIS_CONDITION"
    }
    // ... more objects for other conditions
  ]
}

Guidelines for populating the `conditionalLogic` array:

1.  **Iterate through Rules:** Each distinct `if`, `else if`, or `else` block from the input rules should map to one object in the `conditionalLogic` array.
2.  **`condition` Field:**
    *   This should be a string accurately representing the logical condition from the input rule.
    *   For example, if the input is `if {ccToMV == True}`, the `condition` field should be `"ccToMV == True"`.
    *   If it's an `else` block that doesn't have an explicit condition, you might represent it as `"ELSE_DEFAULT"` or infer the complementary condition if obvious (e.g., if the preceding condition was `"X == Y"`, the `else` might be implicitly `"X != Y"` or a more general default). Use your best judgment to make it clear.
3.  **`codeBlock` Field:**
    *   If the input rule includes an explanatory comment, note, or a block of text (often denoted by `//`, `#`, or explicitly labeled) that provides context *for that specific condition or its logic*, include this text as a string in the `codeBlock` field.
    *   If no such comment/block is present for a rule, you can either omit the `codeBlock` field entirely from that object or set its value to `null`.
4.  **`value` Field:**
    *   This field should contain the outcome, action, or value assigned when the corresponding `condition` is met.
    *   If the outcome is a simple string, the `value` will be that string.
    *   **Important for Complex Values:** If the outcome for a condition is multi-part, has named sub-responses, or is structured (like your example's `noRefund` and `governmentFeesNonRefundable` parts), represent this as accurately as possible.
        *   It could be a single multi-line string where distinct parts are clearly separated.
        *   Alternatively, if the input strongly suggests a key-value structure for the outcome, you can represent the `value` as a JSON object itself (e.g., `{"noRefund": "...", "governmentFeesNonRefundable": "..."}`). Choose the representation that best captures the input's intent and structure. Your example shows a multi-line string where newlines and indentation imply structure; replicate that if it's the input format.

---
Please generate the JSON output based on these inputs and the guidelines."""

BUSINESS_2_TECH_PROMPT = """
You are a developer tasked with transforming business requirements, presented in Markdown format, into a structured representation of code logic. Your goal is to accurately parse the Markdown input and generate an output that reflects the conditional logic and associated outcomes defined in the business requirements.

**Input Format:**

The input will be a block of Markdown text, structured generally as follows:

1.  **Business Function Value:** A line starting with `💡 BUSINESS_FUNCTION_VALUE:` followed by a description. (This is for context).
2.  **Name:** A line starting with `Name*:` followed by a unique identifier for the business function.
3.  **Conditional Blocks:** One or more sections representing conditional logic. Each section will typically consist of:
    *   An `if`, `else if`, or `else` condition. This condition might be presented as a blockquote (e.g., lines starting with `>`) or as a distinct paragraph.
    *   Conditions involve variables, which might be formatted as Markdown links (e.g., `[VariableName](link_url)` or simple names like `‣`).
    *   Conditions involve comparison operators (e.g., `==`, `!=`, `>`, `<`) and values (e.g., `"maid"`, `"CC"`).
    *   Conditions can be compound (e.g., using `&` for AND, `|` for OR).
    *   Each conditional statement will be followed by its associated outcome or result text (e.g., "Delighters.", "CC Resolvers."). This outcome text might be on the immediately following line(s) or within the same structural block.

**Output Format:**

Your output should be structured in Markdown as follows:

1.  **Technical Function Value:**
    *   Start with `💡TECHNICAL_FUNCTION_VALUE:`
    *   The value for this should be derived from the primary variable or concept central to the conditional logic in the input (e.g., if conditions heavily feature `[User_Relationship]`, this might be "User Relationship"). If multiple variables are involved, choose the most prominent one. If no clear variable is central, this might be derived from the `BUSINESS_FUNCTION_VALUE` or `Name*`.

2.  **Parameter Table (Describing the Technical Function Value):**
    *   A markdown table titled "Parameter".
    *   This table specifically describes the primary parameter identified as the `TECHNICAL_FUNCTION_VALUE`.
    *   **Structure:**
        *   Column 1 Header: The literal string `Parameter Name`.
        *   Column 2 Header: The string value of the `Name`.
        *   There will be one data row:
            *   Cell 1 : The literal string `Parameter Link`.
            *   Cell 2 : The hyperlink URL associated with the variable chosen as the `Name`. If that variable was defined with a Markdown link in the input (e.g., `[User_Relationship](url)`), use that URL. If the variable had no link, this cell is empty.
    *   **Example:**
        If `Name: User Relationship` (derived from `[User_Relationship](http://example.com/link)` in input):
        ```markdown
        Parameter

        | Parameter Name | User Relationship |
        | --- | --- |
        | Parameter Link | http://example.com/link |
        ```
        If `Name: OrderStatus` (derived from `[OrderStatus]` in input, no link):
        ```markdown
        Parameter

        | Parameter Name | OrderStatus |
        | --- | --- |
        | Parameter Link |             |
        ```
    *   **Note:** This table *only* describes the parameter designated as the `TECHNICAL_FUNCTION_VALUE`. Other variables used in conditions are not listed in this specific table but will appear in the conditional logic blocks.

3.  **Prompts Table:**
    *   A markdown table titled "Prompts".
    *   Columns: `| Prompt Name | Prompt Link |`
    *   This section should not be populated

4.  **API Endpoint:**
    *   A line starting with `API:`.
    *   This section is populated by looking for markdown links (e.g. (variable_name)[link]) and adding them to the list

5.  **Conditional Logic Blocks:**
    *   For each conditional branch (`if`, `else if`, `else`) found in the input:
        *   **Condition Representation:**
            *   Represent the condition in a code-like syntax (e.g., `if {variableName == "value"}`).
            *   Translate compound conditions (e.g., `&` to `&&`, `|` to `||`).
            *   **Variable Naming in Code:**
                *   For variables like `[User_Relationship]`, convert the name to camelCase (e.g., `userRelationship`).
                *   For symbolic variables (e.g., `‣`), use a descriptive camelCase name if its meaning is clear from context (e.g., `promptSelection`, `customerIntent`). If unclear, use a generic but consistent name (e.g., `symbolVar1`, `specialInput`).
                *   Ensure all variables from the input condition are represented in the output code condition.
            *   Values in conditions should be quoted if they are strings (e.g., `"maid"`).
        *   **Optional Comment:**
            *   Include a comment if context about the variable is easily inferable (e.g., `// local session attribute: userRelationship`). Prioritize information directly from input.
        *   **Value Section:**
            *   Below the condition, include: `- Value:`
            *   List the direct outcome or result text associated with that specific condition from the input as a bullet point (e.g., `- Delighters.`). **Do not add interpretative text or details not explicitly stated in the input's outcome for that condition.**

**General Rules:**

*   **Stick to the Input:** Only include information in the output that is directly present or can be directly derived from the input Markdown. Do not invent or infer details (like specific prompt names, API endpoints, or elaborate value descriptions beyond the direct outcome text) if they are not provided.
*   **Variable Extraction:** Correctly identify all variable names (e.g., `[User_Relationship]`, `‣`) and their associated links (if any) from the input conditions for use in generating the code logic.
*   **Condition Translation:** Accurately and completely translate the input conditions, including all parts of compound conditions, into the specified code-like syntax.
*   **Outcome Mapping:** Ensure each condition correctly maps to its specified outcome text from the input, only map a condition if it is explicitly mentioned.
*   **Empty Fields:** If the input does not provide information for an optional output section (like Prompts or API), that section in the output must be left empty or omitted, as specified.
*   **Markdown Interpretation:** Focus on the semantic structure implied by Markdown (e.g., blockquotes for conditions, subsequent lines for outcomes) rather than any non-standard tags.
*   **Empty Conditions**: If there isn't a value for some condition (usually the word "value" is mentioned) the condition is just used for clarity, and should not be listed at all

**Very Important Rule BUSINESS_FUNCTION_VALUE**: 
*   **Nested BUSINESS_FUNCTION_VALUE**: You might encounter nested BUSINESS_FUNCTION_VALUE blocks, meaning you will find a BUSINESS_FUNCTION_VALUE within the value of some of the conditions. You **MUST** do the same processing for the nested BUSINESS_FUNCTION_VALUE blocks.

### Example:
**Input**:
- 💡 BUSINESS_FUNCTION_VALUE: User relationship.
    
    Name*: User Relationship
    
    <aside>
    <img src="/icons/triangle_gray.svg" alt="/icons/triangle_gray.svg" width="40px" />
    
    > if user=="maid":
    > 
    > - The customer is the maid speaking to you.
    > - Always address her directly as “you” when discussing symptoms or advice.
    > - Her Phone number is {maidPhoneNumber}.
    </aside>
    
    > if user=="client":
    > 
    > - The customer is the client speaking to you.
    > - he patient is the customer’s maid.
    > - Always address the customer in the third person as “your maid” when discussing symptoms or advice.
    > - The client’s maid’s phone number is {maidPhoneNumber}.
    </aside>

**Output**:
- 💡TECHNICAL_FUNCTION_VALUE: User Relationship
    
    Parameter
    
    | Parameter Name | User Relationship |
    | --- | --- |
    | Parameter Link |  |
    
    Prompts
    
    | Prompt Name | Prompt Link |
    | --- | --- |
    | Doctor |  |
    
    API:  /sales/chatretentiongptsession/getuserrelationship
    
    ```jsx
    if { userRelationship  == "maid"}
    // local session attribute: userRelationship
    ```
    
    - Value:
        - The customer is the maid speaking to you.
        - Always address her directly as “you” when discussing symptoms or advice.
        - Her Phone number is {maidPhoneNumber}.
    
    ```jsx
    if { userRelationship  == "client"}
    ```
    
    - Value:
        - The customer is the client speaking to you.
        - The patient is the customer’s maid.
        - Always address the customer in the third person as “your maid” when discussing symptoms or advice.
        - The client’s maid’s phone number is {maidPhoneNumber}.
"""