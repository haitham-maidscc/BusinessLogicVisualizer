import ast
import pandas as pd
from typing import List, Dict, Any
from notion_utils import extract_table_data
from notion_client import Client
from dotenv import load_dotenv, find_dotenv
import logging

# Configure logging
logger = logging.getLogger(__name__)

load_dotenv(".env")

_SPEC_BLOCK_NAME_DEFAULT = "💡TECHNICAL_FUNCTION_VALUE:"

# --- Helper functions for processing loaded blocks ---

def load_blocks_from_file(filepath: str) -> List[Dict[str, Any]]:
    """Loads a list of block dictionaries from a text file."""
    logger.info(f"Loading blocks from file: {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        blocks = ast.literal_eval(content)
        if not isinstance(blocks, list):
            logger.error("File content is not a list")
            raise ValueError("File content is not a list.")
        for block_idx, block_item in enumerate(blocks):
            if not isinstance(block_item, dict):
                logger.error(f"Item at index {block_idx} in the list is not a dictionary")
                raise ValueError(f"Item at index {block_idx} in the list is not a dictionary.")
        logger.info(f"Successfully loaded {len(blocks)} blocks from file")
        return blocks
    except FileNotFoundError:
        logger.error(f"File not found at {filepath}")
        return []
    except (SyntaxError, ValueError) as e:
        logger.error(f"Error parsing file content: {str(e)}")
        return []

def get_block_plain_text(block: Dict[str, Any], params) -> str:
    """
    Extracts plain text content from a Notion block.
    Handles common block types.
    """
    logger.debug(f"Extracting plain text from block type: {block.get('type')}")
    block_type = block.get("type")
    text_content = ""

    # Common structure for types with rich_text array
    rich_text_key_map = {
        # "paragraph": "paragraph",
        # "heading_1": "heading_1",
        # "heading_2": "heading_2",
        # "heading_3": "heading_3",
        # "bulleted_list_item": "bulleted_list_item",
        # "numbered_list_item": "numbered_list_item",
        "quote": "quote",
        # "callout": "callout",
        "toggle": "toggle", # Toggle title text
        # "code": "code" # Code block content
    }

    if block_type in rich_text_key_map:
        type_specific_key = rich_text_key_map[block_type]
        rich_text_array = block.get(type_specific_key, {}).get("rich_text", [])
        for rt_segment in rich_text_array:
            if rt_segment.get("type") == "text":
                text_content += rt_segment.get("text", {}).get("content", "")
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

def get_all_descendants_content_with_indent(
    spec_block_id: str,
    spec_block_level: int,
    all_blocks_map: Dict[str, Dict[str, Any]],
    blocks_by_parent_id: Dict[str, List[Dict[str, Any]]],
    params
) -> str:
    """
    Recursively fetches all descendant blocks of a given spec_block_id,
    concatenates their text content, with indentation based on their level
    relative to the spec_block.
    """
    logger.info(f"Getting descendants content for spec block: {spec_block_id}")
    concatenated_text_lines: List[str] = []
    processed_blocks_in_this_traversal = set()

    def _recursive_collect_text(current_block_id_to_process: str):
        if current_block_id_to_process in processed_blocks_in_this_traversal:
            logger.debug(f"Skipping already processed block: {current_block_id_to_process}")
            return
        processed_blocks_in_this_traversal.add(current_block_id_to_process)

        block = all_blocks_map.get(current_block_id_to_process)
        if not block:
            logger.warning(f"Block {current_block_id_to_process} referenced as child but not found in all_blocks_map")
            return

        current_block_abs_level = block.get('level')
        if current_block_abs_level is None:
            logger.warning(f"Block {block.get('id', 'Unknown ID')} (type: {block.get('type')}) is missing 'level' attribute. Using default indentation.")
            num_tabs = 1
        else:
            num_tabs = current_block_abs_level - spec_block_level
            if num_tabs <= 0:
                logger.debug(f"Non-positive tab count ({num_tabs}) for block {block['id']}, using default indentation")
                num_tabs = 1

        block_text_content = get_block_plain_text(block, params)
        if block_text_content:
            lines_from_block = block_text_content.split('\n')
            for line in lines_from_block:
                indented_line = ("\t" * num_tabs) + line
                concatenated_text_lines.append(indented_line)

        child_ids_of_current = [child['id'] for child in blocks_by_parent_id.get(current_block_id_to_process, [])]
        for child_id in child_ids_of_current:
            _recursive_collect_text(child_id)

    direct_children_ids = [child['id'] for child in blocks_by_parent_id.get(spec_block_id, [])]
    logger.debug(f"Found {len(direct_children_ids)} direct children for spec block {spec_block_id}")
    for child_id in direct_children_ids:
        _recursive_collect_text(child_id)

    logger.info(f"Processed {len(processed_blocks_in_this_traversal)} blocks for spec block {spec_block_id}")
    return "\n".join(concatenated_text_lines)

def process_notion_blocks_from_file(
    input_filepath: str,
    output_csv_filepath: str,
    spec_block_identifier: str = _SPEC_BLOCK_NAME_DEFAULT,
    params: dict = {}
):
    logger.info(f"Processing Notion blocks from file: {input_filepath}")
    all_blocks = load_blocks_from_file(input_filepath)
    if not all_blocks or len(all_blocks)==0:
        logger.warning("No blocks loaded, exiting")
        return all_blocks

    all_blocks_map: Dict[str, Dict[str, Any]] = {}
    for block in all_blocks:
        if 'id' not in block:
            logger.warning(f"Block found without an ID: {str(block)[:100]}. Skipping for map.")
            continue
        all_blocks_map[block['id']] = block

    blocks_by_parent_id: Dict[str, List[Dict[str, Any]]] = {}
    for block in all_blocks:
        if 'id' not in block:
            continue
        parent_info = block.get("parent", {})
        parent_id = parent_info.get("block_id") or \
                    parent_info.get("page_id") or \
                    parent_info.get("database_id")
        if parent_id:
            if parent_id not in blocks_by_parent_id:
                blocks_by_parent_id[parent_id] = []
            blocks_by_parent_id[parent_id].append(block)

    logger.info(f"Processed {len(all_blocks_map)} blocks into maps")
    spec_blocks_data = []
    
    identified_spec_blocks = []
    for block in all_blocks:
        if block.get("type") == "toggle":
            toggle_title_text = get_block_plain_text(block, params)
            if spec_block_identifier in toggle_title_text:
                if 'id' not in block:
                    logger.warning(f"Spec toggle found without ID: '{toggle_title_text}'. Skipping.")
                    continue
                if 'level' not in block:
                    logger.warning(f"Spec toggle '{toggle_title_text}' (ID: {block.get('id')}) is missing 'level' attribute. Indentation may be incorrect.")
                identified_spec_blocks.append(block)

    if not identified_spec_blocks:
        logger.warning(f"No spec blocks found with identifier '{spec_block_identifier}'")
        return

    logger.info(f"Found {len(identified_spec_blocks)} spec blocks")
    for spec_block in identified_spec_blocks:
        spec_block_id = spec_block["id"]
        spec_block_name_full = get_block_plain_text(spec_block, params)
        spec_block_name_clean = spec_block_name_full.replace(spec_block_identifier, "").strip()
        
        spec_block_level = spec_block.get('level')
        if spec_block_level is None:
            logger.warning(f"Spec block '{spec_block_name_clean}' (ID: {spec_block_id}) has no 'level' attribute. Using default level 0.")
            spec_block_level = 0

        logger.info(f"Processing spec block: {spec_block_name_clean}")
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
        logger.warning("No data to write to CSV (spec blocks found but had no processable children or content)")
        return

    try:
        logger.info(f"Writing {len(spec_blocks_data)} spec blocks to CSV: {output_csv_filepath} using pandas")
        fieldnames = ["block_name", "block_content"]
        df = pd.DataFrame(spec_blocks_data, columns=fieldnames)
        df.to_csv(output_csv_filepath, index=False, encoding='utf-8')
        logger.info(f"Successfully wrote data to {output_csv_filepath}")
        return df
    except IOError as e:
        logger.error(f"Error writing CSV file: {str(e)}")
        raise

def process_spec_blocks(block_identifier:str, page_id: str, table_page_id: str, notion_client: Client):
    logger.info(f"Processing spec blocks for page: {page_id}, table: {table_page_id}")
    # --- Configuration ---
    INPUT_TEXT_FILE = f"blocks/{page_id}_all_blocks.txt"
    OUTPUT_CSV_FILE = f"{page_id}_spec_block_contents.csv"

    logger.info("Extracting table data from Notion")
    params = extract_table_data(table_page_id, notion_client)

    # --- Run the processing ---
    df = process_notion_blocks_from_file(
        INPUT_TEXT_FILE,
        OUTPUT_CSV_FILE,
        block_identifier,
        params
    )

    logger.info(f"Reading processed data from {OUTPUT_CSV_FILE}")
    return df