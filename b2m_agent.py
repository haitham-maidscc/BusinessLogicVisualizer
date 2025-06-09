import os
import base64
import requests
import tempfile
from typing import TypedDict, List
from dotenv import load_dotenv, find_dotenv

import pandas as pd

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END

# Load environment variables
load_dotenv(find_dotenv(), override=True)

# --- 1. State Definition ---
class AgentState(TypedDict):
    llm: BaseChatModel
    original_logic: str
    clarified_logic: str
    mermaid_graph: str
    validation_result: str  # "valid", "invalid"
    error_message: str
    max_retries: int
    current_retry: int
    feedback_history: List[str]

# --- 2. Tools ---
@tool
def validate_mermaid_syntax(mermaid_code: str) -> str:
    """
    Validates the provided Mermaid diagram syntax using the mermaid.ink API.
    Returns "Graph is valid" if no errors are found.
    Otherwise, returns a string starting with "Error:" followed by the error details.
    """
    print(f"--- Validating Mermaid Code via mermaid.ink API ---\n{mermaid_code}\n---")

    # 1. Prepare the code for validation (remove markdown backticks)
    code_to_validate = mermaid_code.strip()
    if code_to_validate.startswith("```mermaid"):
        code_to_validate = code_to_validate[len("```mermaid"):]
    if code_to_validate.endswith("```"):
        code_to_validate = code_to_validate[:-len("```")]
    code_to_validate = code_to_validate.strip()

    if not code_to_validate:
        return "Error: Mermaid code is empty after stripping backticks."

    try:
        # Encode the Mermaid code
        graphbytes = code_to_validate.encode("utf8")
        base64_bytes = base64.urlsafe_b64encode(graphbytes)
        base64_string = base64_bytes.decode("ascii")

        # Make the request to mermaid.ink API
        url = f'https://mermaid.ink/svg/{base64_string}'
        response = requests.get(url, timeout=15)

        if response.status_code == 200:
            print("Validation successful: Graph is valid")
            return "Graph is valid"
        else:
            error_message = response.text if response.text else f"HTTP {response.status_code}"
            print(f"Validation failed: {error_message}")
            return f"Error: Mermaid syntax validation failed.\nAPI Response: {error_message}"

    except requests.Timeout:
        return "Error: Validation request timed out. The Mermaid diagram might be too complex."
    except requests.RequestException as e:
        return f"Error: Failed to validate Mermaid syntax. API request failed: {str(e)}"
    except Exception as e:
        return f"Error: An unexpected error occurred during validation: {str(e)}"

def clarify_logic_node(state: AgentState) -> AgentState:
    print("--- Clarifying Business Logic Node ---")
    llm = state["llm"]
    original_logic = state["original_logic"]

    prompt = f"""
    You are an AI assistant that refines business logic to make it clearer for another AI to generate a Mermaid flowchart.
    Review the following business logic. If it seems ambiguous, too complex in its current phrasing, or likely to cause issues for a flowchart generator, you can edit it to make it clear without completely changing it.
    Ensure conditions are explicit, and outcomes are clearly associated.
    If the logic already seems clear and well-structured for flowchart generation, output it as is.

    Key considerations for the flowchart generator:
    - It needs to identify distinct conditions.
    - It needs to map conditions to specific values or outcomes.
    - If a variable is checked against multiple values (e.g., client_type == "A", client_type == "B"), this structure should be very clear.

    Original Business Logic:
    {original_logic}

    If you rewrite it, provide ONLY the rewritten logic. If no rewrite is needed, return the original logic.
    """

    response = llm.invoke([HumanMessage(content=prompt)])
    clarified_logic = response.content.strip()

    print(f"Clarified Logic:\n{clarified_logic}")

    return {"clarified_logic": clarified_logic, "current_retry": 0, "feedback_history": []}

def generate_mermaid_node(state: AgentState) -> AgentState:
    print("--- Generating Mermaid Graph Node ---")
    llm = state["llm"]
    logic_to_use = state["original_logic"]
    feedback_items = state.get("feedback_history", [])

    feedback_intro = ""
    if feedback_items:
        feedback_intro = "\n**Review the following feedback from previous attempts and address the issues:**\n"
        recent_feedback = "\n---\n".join(feedback_items[-3:])
        feedback_intro += recent_feedback

    prompt_template = f"""
    You are an expert in generating Mermaid flowchart diagrams from business logic.
    Convert the following business logic into a Mermaid flowchart (`graph TD` or `flowchart TD`).

    **Important Instructions:**
    1.  **Syntax**: Ensure your output is valid Mermaid syntax. Pay close attention to node IDs, edge definitions (e.g., `A --> B`), and subgraph syntax if used.
        *   Node IDs must be alphanumeric and cannot contain special characters like spaces, hyphens (unless part of a quoted label), or periods directly in the ID. If you need spaces or special characters in the *displayed text* of a node, use quotes: `id1["Node Text with Spaces"]`.
        *   Ensure all declared nodes are used or connected.
    2.  **Decision Nodes**: Represent conditions as diamond shapes. Example: `condition1{{Is X true?}}`.
    3.  **Multi-Value Conditions**: If a condition checks a single variable against multiple distinct values (e.g., `if client_type == "type1"`, then `if client_type == "type2"`), the decision node for `client_type` should have edges directly labeled with these values (e.g., `client_type_check{{Client Type?}} -->|type1| outcome1`, `client_type_check -- type2 --> outcome2`). Do NOT use generic "true"/"false" edges for these cases.
    4.  **Values**: The values for the conditions are always placeholders, that's why you will see "[value]", however, this does not mean that they all share the same value each one should have a separate [value] node.
    5.  **Clarity and Readability**: Ensure the graph is easy to understand and accurately reflects the logic. Start with `graph TD` or `flowchart TD`.
    6.  **Output Format**: Provide ONLY the Mermaid code block, starting with ```mermaid and ending with ```. No other text or explanation before or after the code block.
    7.  **List all Conditions**: never forget to add any of the listed conditions.
    8.  **Long Text Values**: even you get a long text as value (e.g "if not condition is met [a long text]") for a condition you should omit it and use "[value]" for the result node.
    9.  **Important Rule**: always put the string inside curly or square brackets between qoutations. 

    **Business Logic to Convert:**
    {logic_to_use}
    {feedback_intro}

    Generate the Mermaid code:
    """
    print(prompt_template)
    response = llm.invoke([HumanMessage(content=prompt_template)])
    mermaid_code = response.content.strip()

    if not mermaid_code.startswith("```mermaid"):
        mermaid_code = "```mermaid\n" + mermaid_code
    if not mermaid_code.endswith("```"):
        mermaid_code = mermaid_code + "\n```"

    print(f"Generated Mermaid Code (Attempt {state.get('current_retry', 0) + 1}):\n{mermaid_code}")

    current_retry = state.get("current_retry", 0) + 1
    return {"mermaid_graph": mermaid_code, "current_retry": current_retry}

def validate_graph_node(state: AgentState) -> AgentState:
    print("--- Validating Mermaid Graph Node ---")
    mermaid_code = state["mermaid_graph"]

    validation_output = validate_mermaid_syntax.invoke({"mermaid_code": mermaid_code})
    print(f"Validation Output: {validation_output}")

    if validation_output == "Graph is valid":
        return {"validation_result": "valid", "error_message": ""}
    else:
        error_message = validation_output
        feedback_history = state.get("feedback_history", [])

        feedback_entry = f"Attempt {state.get('current_retry', 1)} failed validation. Error: {error_message}"
        if "Generated Code:" in error_message:
            feedback_entry = f"Attempt {state.get('current_retry', 1)} failed validation. Error: {error_message.split('Generated Code:')[0].strip()}"

        feedback_history.append(feedback_entry)
        return {"validation_result": "invalid", "error_message": error_message, "feedback_history": feedback_history}

def should_retry_generation(state: AgentState) -> str:
    print("--- Decision: Should Retry Generation? ---")
    if state["validation_result"] == "valid":
        print("Decision: Graph is valid. End.")
        return "end_process"
    else:
        if state["current_retry"] < state["max_retries"]:
            print(f"Decision: Validation failed. Retry {state['current_retry']}/{state['max_retries']}.")
            return "regenerate_graph"
        else:
            print(f"Decision: Validation failed. Max retries ({state['max_retries']}) reached. End with error.")
            return "end_with_error"

def build_mermaid_agent():
    workflow = StateGraph(AgentState)

    # workflow.add_node("clarify_logic", clarify_logic_node)
    workflow.add_node("generate_mermaid", generate_mermaid_node)
    workflow.add_node("validate_graph", validate_graph_node)
    workflow.add_node("final_error_node", lambda state: print(f"--- Max retries reached. Process failed. Last error: {state.get('error_message', 'N/A')} ---") or END)

    # workflow.set_entry_point("clarify_logic")
    # workflow.add_edge("clarify_logic", "generate_mermaid")
    workflow.set_entry_point("generate_mermaid")
    workflow.add_edge("generate_mermaid", "validate_graph")

    workflow.add_conditional_edges(
        "validate_graph",
        should_retry_generation,
        {
            "regenerate_graph": "generate_mermaid",
            "end_process": END,
            "end_with_error": "final_error_node"
        }
    )

    app = workflow.compile()
    return app

def run_agent(app, llm: BaseChatModel, business_logic_text: str, max_retries=3):
    inputs = {
        "original_logic": business_logic_text,
        "llm": llm,
        "max_retries": max_retries,
        "current_retry": 0,
        "feedback_history": []
    }

    print("\n--- Running Agent ---")
    final_state = app.invoke(inputs)

    print("\n--- Agent Finished ---")
    if final_state.get("validation_result") == "valid":
        print("\nSuccessfully generated and validated Mermaid graph:")
        print(final_state["mermaid_graph"])
        return final_state["mermaid_graph"]
    else:
        print("\nFailed to generate a valid Mermaid graph after retries.")
        print(f"Last Error: {final_state.get('error_message', 'Unknown error')}")
        if final_state.get("mermaid_graph"):
            print("Last Attempted Graph (which failed validation):")
            print(final_state["mermaid_graph"])

        print("\nReview feedback history given to LLM during retries:")
        if final_state.get("feedback_history"):
            for i, item in enumerate(final_state.get("feedback_history", [])):
                print(f"Feedback for attempt {i+1}:\n{item}\n")
        else:
            print("No feedback history recorded (or first attempt failed).")