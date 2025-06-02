import ast
import csv
import os
import pandas as pd
from typing import List, Dict, Any
from notion_utils import extract_table_data
from notion_client import Client
from dotenv import load_dotenv, find_dotenv
load_dotenv(".env")

_SPEC_BLOCK_NAME_DEFAULT = "💡TECHNICAL_FUNCTION_VALUE:"

# --- Helper functions for processing loaded blocks ---

def load_blocks_from_file(filepath: str) -> List[Dict[str, Any]]:
    """Loads a list of block dictionaries from a text file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        blocks = ast.literal_eval(content)
        if not isinstance(blocks, list):
            raise ValueError("File content is not a list.")
        for block_idx, block_item in enumerate(blocks):
            if not isinstance(block_item, dict):
                raise ValueError(f"Item at index {block_idx} in the list is not a dictionary.")
        return blocks
    except FileNotFoundError:
        print(f"Error: File not found at {filepath}")
        return []
    except (SyntaxError, ValueError) as e:
        print(f"Error parsing file content: {e}")
        return []

def get_block_plain_text(block: Dict[str, Any], params) -> str:
    """
    Extracts plain text content from a Notion block.
    Handles common block types.
    """
    block_type = block.get("type")
    text_content = ""

    # Common structure for types with rich_text array
    rich_text_key_map = {
        "paragraph": "paragraph",
        "heading_1": "heading_1",
        "heading_2": "heading_2",
        "heading_3": "heading_3",
        "bulleted_list_item": "bulleted_list_item",
        "numbered_list_item": "numbered_list_item",
        "quote": "quote",
        "callout": "callout",
        "toggle": "toggle", # Toggle title text
        "code": "code" # Code block content
    }

    if block_type in rich_text_key_map:
        type_specific_key = rich_text_key_map[block_type]
        rich_text_array = block.get(type_specific_key, {}).get("rich_text", [])
        for rt_segment in rich_text_array:
            if rt_segment.get("type") == "text":
                text_content += rt_segment.get("text", {}).get("content", "")
            # Optionally handle mentions, equations etc. if needed
            elif rt_segment.get("type") == "mention": 
                erp_param = params.get(rt_segment["mention"][rt_segment["mention"]["type"]]["id"].replace("-", ""), {})
                text_content += (erp_param.get("API Parameter Name", erp_param.get("Name", "[Variable Name Missing]"))
                    if erp_param.get("API Parameter Name") else erp_param.get("Name", "[Variable Name Missing]"))

    elif block_type == "child_page":
        text_content = block.get("child_page", {}).get("title", "")
    elif block_type == "table_of_contents":
        text_content = "[Table of Contents]"
    elif block_type == "divider":
        text_content = "---"
    # Add more block types as needed: image, video, file, table etc.

    return text_content
    # Note: .strip() is not used here to preserve potential leading/trailing whitespace
    # in code blocks or intentionally formatted text. Tabs will be prepended.

def get_all_descendants_content_with_indent(
    spec_block_id: str,
    spec_block_level: int, # Absolute level of the spec block itself
    all_blocks_map: Dict[str, Dict[str, Any]],
    blocks_by_parent_id: Dict[str, List[Dict[str, Any]]],
    params
) -> str:
    """
    Recursively fetches all descendant blocks of a given spec_block_id,
    concatenates their text content, with indentation based on their level
    relative to the spec_block.
    """
    concatenated_text_lines: List[str] = []
    processed_blocks_in_this_traversal = set()

    def _recursive_collect_text(current_block_id_to_process: str):
        if current_block_id_to_process in processed_blocks_in_this_traversal:
            return
        processed_blocks_in_this_traversal.add(current_block_id_to_process)

        block = all_blocks_map.get(current_block_id_to_process)
        if not block:
            # This might happen if a block is listed as a child but isn't in all_blocks_map
            print(f"Warning: Block {current_block_id_to_process} referenced as child but not found in all_blocks_map.")
            return

        current_block_abs_level = block.get('level')
        if current_block_abs_level is None:
            print(f"Warning: Block {block.get('id', 'Unknown ID')} (type: {block.get('type')}) is missing 'level' attribute. Indentation might be incorrect, defaulting to 1 tab.")
            num_tabs = 1 # Fallback if level is missing, assuming it's at least a direct child
        else:
            # Calculate tabs relative to the spec_block's level.
            # Example: spec_block (level 0), its child (level 1) -> num_tabs = 1 - 0 = 1.
            # Example: spec_block (level 1), its child (level 2) -> num_tabs = 2 - 1 = 1.
            num_tabs = current_block_abs_level - spec_block_level
            
            # Children should always have a greater level than their spec_block parent.
            # If num_tabs is not positive, it implies inconsistent level data or a non-child.
            if num_tabs <= 0:
                # print(f"Debug: num_tabs calculated as {num_tabs} for block {block['id']} (level {current_block_abs_level}) "
                #       f"relative to spec_block_level {spec_block_level}. Assuming it's a direct child with 1 tab.")
                num_tabs = 1 # Fallback: ensure at least one tab for (assumed) children.

        block_text_content = get_block_plain_text(block, params)
        if block_text_content: # Only add if there's actual text from the block
            lines_from_block = block_text_content.split('\n')
            for line in lines_from_block:
                indented_line = ("\t" * num_tabs) + line
                concatenated_text_lines.append(indented_line)

        # Recursively process children of the current block
        child_ids_of_current = [child['id'] for child in blocks_by_parent_id.get(current_block_id_to_process, [])]
        for child_id in child_ids_of_current:
            _recursive_collect_text(child_id) # spec_block_level remains constant for context

    # Start recursion with the direct children of the spec_block_id
    direct_children_ids = [child['id'] for child in blocks_by_parent_id.get(spec_block_id, [])]
    for child_id in direct_children_ids:
        _recursive_collect_text(child_id)

    return "\n".join(concatenated_text_lines)


def process_notion_blocks_from_file(
    input_filepath: str,
    output_csv_filepath: str,
    spec_block_identifier: str = _SPEC_BLOCK_NAME_DEFAULT,
    params: dict = {}
):
    all_blocks = load_blocks_from_file(input_filepath)
    if not all_blocks:
        print("No blocks loaded, exiting.")
        return

    all_blocks_map: Dict[str, Dict[str, Any]] = {}
    for block in all_blocks:
        if 'id' not in block:
            print(f"Warning: Block found without an ID: {str(block)[:100]}. Skipping for map.")
            continue
        all_blocks_map[block['id']] = block

    blocks_by_parent_id: Dict[str, List[Dict[str, Any]]] = {}
    for block in all_blocks:
        if 'id' not in block:
            continue
        parent_info = block.get("parent", {})
        parent_id = parent_info.get("block_id") or \
                    parent_info.get("page_id") or \
                    parent_info.get("database_id") # child_database blocks have parent_type database_id
        if parent_id:
            if parent_id not in blocks_by_parent_id:
                blocks_by_parent_id[parent_id] = []
            blocks_by_parent_id[parent_id].append(block)

    spec_blocks_data = []
    
    identified_spec_blocks = []
    for block in all_blocks:
        if block.get("type") == "toggle":
            # Use get_block_plain_text to extract the toggle's title for checking
            toggle_title_text = get_block_plain_text(block, params)
            if spec_block_identifier in toggle_title_text:
                if 'id' not in block:
                    print(f"Warning: Spec toggle found without ID: '{toggle_title_text}'. Skipping.")
                    continue
                if 'level' not in block:
                    # This is crucial for indentation.
                    print(f"Warning: Spec toggle '{toggle_title_text}' (ID: {block.get('id')}) is missing 'level' attribute. Indentation of children may be incorrect.")
                identified_spec_blocks.append(block)

    if not identified_spec_blocks:
        print(f"No spec blocks found with identifier '{spec_block_identifier}'.")
        return

    for spec_block in identified_spec_blocks:
        spec_block_id = spec_block["id"]
        # Clean the spec_block_identifier from the name for the CSV
        spec_block_name_full = get_block_plain_text(spec_block, params)
        spec_block_name_clean = spec_block_name_full.replace(spec_block_identifier, "").strip()
        
        spec_block_level = spec_block.get('level')
        if spec_block_level is None:
            # This is a critical piece of info for correct relative indentation.
            print(f"CRITICAL: Spec block '{spec_block_name_clean}' (ID: {spec_block_id}) has no 'level' attribute. "
                  f"Defaulting spec_block_level to 0, but child indentations may be inaccurate.")
            spec_block_level = 0 # Fallback, but could lead to issues if the spec block was actually nested.

        descendant_content = get_all_descendants_content_with_indent(
            spec_block_id=spec_block_id,
            spec_block_level=spec_block_level,
            all_blocks_map=all_blocks_map,
            blocks_by_parent_id=blocks_by_parent_id,
            params=params
        )
        
        spec_blocks_data.append({
            "block_name": spec_block_name_clean,
            "block_content": descendant_content
        })

    if not spec_blocks_data:
        print("No data to write to CSV (e.g., spec blocks found but had no processable children or content).")
        return

    try:
        with open(output_csv_filepath, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ["block_name", "block_content"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row_data in spec_blocks_data:
                writer.writerow(row_data)
        print(f"Successfully wrote data to {output_csv_filepath}")
    except IOError as e:
        print(f"Error writing CSV file: {e}")

def process_spec_blocks(block_identifier:str, page_id: str, table_page_id: str, notion_client: Client):
    # --- Configuration ---
    INPUT_TEXT_FILE = f"blocks/{page_id}_all_blocks.txt"  # Path to your text file containing the blocks
    OUTPUT_CSV_FILE = f"{page_id}_spec_block_contents.csv"
    # If your spec block identifier is different, change it here

    params = extract_table_data(table_page_id, notion_client)

    # --- Run the processing ---
    process_notion_blocks_from_file(
        INPUT_TEXT_FILE,
        OUTPUT_CSV_FILE,
        block_identifier,
        params
    )

    return pd.read_csv(OUTPUT_CSV_FILE)