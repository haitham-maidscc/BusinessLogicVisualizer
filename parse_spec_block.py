import ast
import pandas as pd
from typing import List, Dict, Any
from notion_utils import extract_table_data # Assuming this exists and is correct
from notion_client import Client
from dotenv import load_dotenv, find_dotenv
import logging

# Configure logging
logger = logging.getLogger(__name__)
# Basic logging configuration for testing if not set elsewhere
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


load_dotenv(".env") # Ensure .env is in the right place or use find_dotenv()

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
        return [] # Return empty list, let caller handle
    except (SyntaxError, ValueError) as e:
        logger.error(f"Error parsing file content: {str(e)}")
        return [] # Return empty list, let caller handle

def get_block_plain_text(block: Dict[str, Any], params: Dict[str, Any]) -> str:
    """
    Extracts plain text content from a Notion block.
    Handles common block types.
    """
    logger.debug(f"Extracting plain text from block type: {block.get('type')}")
    block_type = block.get("type")
    text_content = ""

    rich_text_key_map = {
        "paragraph": "paragraph", "heading_1": "heading_1", "heading_2": "heading_2",
        "heading_3": "heading_3", "bulleted_list_item": "bulleted_list_item",
        "numbered_list_item": "numbered_list_item", "quote": "quote", "callout": "callout",
        "toggle": "toggle", "code": "code"
    }

    if block_type in rich_text_key_map:
        type_specific_key = rich_text_key_map[block_type]
        rich_text_array = block.get(type_specific_key, {}).get("rich_text", [])
        for rt_segment in rich_text_array:
            if rt_segment.get("type") == "text":
                text_content += rt_segment.get("text", {}).get("content", "")
            elif rt_segment.get("type") == "mention":
                mention_data = rt_segment.get("mention", {})
                mention_type = mention_data.get("type")
                if mention_type and mention_type in mention_data:
                    mention_id_obj = mention_data[mention_type]
                    if isinstance(mention_id_obj, dict) and "id" in mention_id_obj:
                        page_id_for_params = mention_id_obj["id"].replace("-", "")
                        erp_param = params.get(page_id_for_params, {})
                        # Prioritize API Parameter Name, then Name, then a placeholder
                        name_to_use = erp_param.get("API Parameter Name")
                        if not name_to_use:
                            name_to_use = erp_param.get("Name")
                        if not name_to_use:
                            name_to_use = "[Variable Name Missing]"
                        text_content += name_to_use
                    else:
                        logger.warning(f"Mention of type '{mention_type}' has unexpected structure: {mention_id_obj}")
                        text_content += "[Malformed Mention]"
                else:
                    logger.warning(f"Mention data is missing type or type-specific data: {mention_data}")
                    text_content += "[Unknown Mention]"
    elif block_type == "child_page":
        text_content = block.get("child_page", {}).get("title", "")
    elif block_type == "table_of_contents":
        text_content = "[Table of Contents]"
    elif block_type == "divider":
        text_content = "---"
    return text_content

def build_spec_content_string_with_quote_logic(
    current_parent_block_id: str,
    spec_toggle_absolute_level: int,
    all_blocks_map: Dict[str, Dict[str, Any]],
    blocks_by_parent_id: Dict[str, List[Dict[str, Any]]],
    params: dict,
    processed_block_ids_in_this_traversal: set
) -> List[str]:
    """
    Recursively processes blocks. If a quote is found, processes it (and same-level
    quote siblings) and then returns, stopping further processing for that parent's children.
    """
    lines_for_this_level: List[str] = []
    children_of_current_parent = blocks_by_parent_id.get(current_parent_block_id, [])
    
    current_child_loop_idx = 0
    while current_child_loop_idx < len(children_of_current_parent):
        child_block_summary = children_of_current_parent[current_child_loop_idx]
        child_id = child_block_summary.get('id')

        if not child_id:
            logger.warning(f"Child summary missing ID under parent {current_parent_block_id}. Skipping.")
            current_child_loop_idx += 1
            continue

        # Check if already processed in this SPECIFIC spec_toggle's traversal.
        # This is a safeguard; child_idx management should prevent most re-processing.
        if child_id in processed_block_ids_in_this_traversal:
            logger.debug(f"Block {child_id} already processed in this traversal. Skipping outer loop processing for it.")
            current_child_loop_idx += 1
            continue

        block = all_blocks_map.get(child_id)
        if not block:
            logger.warning(f"Block {child_id} (child of {current_parent_block_id}) not found in all_blocks_map. Skipping.")
            current_child_loop_idx += 1
            continue
        
        # Mark this block as handled for the current spec_toggle's output generation.
        # This add is crucial and should happen before any conditional processing or recursion for this block.
        processed_block_ids_in_this_traversal.add(child_id)

        current_block_abs_level = block.get('level')
        if current_block_abs_level is None:
            logger.warning(f"Block {block.get('id', 'Unknown ID')} (type: {block.get('type')}) missing 'level'. Using default relative indent of 1.")
            num_tabs = 1 
        else:
            num_tabs = current_block_abs_level - spec_toggle_absolute_level
        
        if num_tabs <= 0:
            num_tabs = 1

        block_type = block.get("type")

        if block_type == "quote":
            # --- Quote Block Special Handling ---
            quote_text = get_block_plain_text(block, params).strip()
            line_content = f"{quote_text}\n[value]" if quote_text else "[value]"
            indented_line = ("\t" * num_tabs) + line_content
            lines_for_this_level.append(indented_line)
            logger.debug(f"Processed quote block {child_id} at level {current_block_abs_level}: {indented_line}")

            first_quote_in_sequence_level = current_block_abs_level
            
            sibling_scan_idx = current_child_loop_idx + 1
            while sibling_scan_idx < len(children_of_current_parent):
                next_sibling_summary = children_of_current_parent[sibling_scan_idx]
                next_sibling_id = next_sibling_summary.get('id')

                if not next_sibling_id:
                    sibling_scan_idx += 1
                    continue
                
                # If this sibling was already added to processed_block_ids (e.g., by an earlier, separate call),
                # it means it's not truly part of *this specific sequence starting now*.
                if next_sibling_id in processed_block_ids_in_this_traversal:
                    logger.debug(f"Sibling {next_sibling_id} already processed. Ending quote sequence scan.")
                    break 

                next_sibling_block = all_blocks_map.get(next_sibling_id)
                if not next_sibling_block:
                    sibling_scan_idx += 1
                    continue
                
                sibling_abs_level = next_sibling_block.get("level")

                if next_sibling_block.get("type") == "quote" and \
                   sibling_abs_level == first_quote_in_sequence_level:
                    
                    # Mark this subsequent quote as processed *as part of this sequence*.
                    processed_block_ids_in_this_traversal.add(next_sibling_id)

                    sibling_quote_text = get_block_plain_text(next_sibling_block, params).strip()
                    sibling_line_content = f"{sibling_quote_text}[value]" if sibling_quote_text else "[value]"
                    indented_sibling_line = ("\t" * num_tabs) + sibling_line_content # Same indent as first quote
                    lines_for_this_level.append(indented_sibling_line)
                    logger.debug(f"Processed subsequent quote block {next_sibling_id} at level {sibling_abs_level}: {indented_sibling_line}")
                    
                    current_child_loop_idx = sibling_scan_idx # Advance the main loop's index past this consumed sibling
                else:
                    break # End of quote sequence
                sibling_scan_idx += 1
            
            # CRITICAL CHANGE: After processing a quote sequence, stop processing further children for THIS PARENT.
            logger.debug(f"Quote sequence processed for parent {current_parent_block_id}. Returning early.")
            return lines_for_this_level 
        
        else: # --- Non-Quote Block Handling ---
            block_text_content = get_block_plain_text(block, params)
            if block_text_content: 
                block_lines = block_text_content.split('\n')
                for line in block_lines:
                    indented_line = ("\t" * num_tabs) + line
                    lines_for_this_level.append(indented_line)
            
            if block.get("has_children"):
                 logger.debug(f"Recursively processing children of non-quote block {child_id}")
                 children_lines = build_spec_content_string_with_quote_logic(
                     child_id, 
                     spec_toggle_absolute_level, 
                     all_blocks_map, 
                     blocks_by_parent_id, 
                     params,
                     processed_block_ids_in_this_traversal # Pass the same set
                 )
                 lines_for_this_level.extend(children_lines)

        current_child_loop_idx += 1
    
    return lines_for_this_level


def process_notion_blocks_from_file(
    input_filepath: str,
    output_csv_filepath: str,
    spec_block_identifier: str = _SPEC_BLOCK_NAME_DEFAULT,
    params: dict = {}
):
    logger.info(f"Processing Notion blocks from file: {input_filepath}")
    all_blocks = load_blocks_from_file(input_filepath)
    if not all_blocks: # Handles empty list from load_blocks_from_file
        logger.warning("No blocks loaded from file, exiting processing.")
        return pd.DataFrame(columns=["block_name", "block_content"])

    all_blocks_map: Dict[str, Dict[str, Any]] = {}
    for block in all_blocks:
        if 'id' not in block:
            logger.warning(f"Block found without an ID: {str(block)[:100]}. Skipping for map.")
            continue
        all_blocks_map[block['id']] = block

    blocks_by_parent_id: Dict[str, List[Dict[str, Any]]] = {}
    for block in all_blocks:
        if 'id' not in block:
            continue # Should have been caught by map population, but defensive.
        parent_info = block.get("parent", {})
        parent_id = parent_info.get("block_id") or \
                    parent_info.get("page_id") or \
                    parent_info.get("database_id")
        if parent_id: # We only care about blocks parented by other blocks/pages/databases
            if parent_id not in blocks_by_parent_id:
                blocks_by_parent_id[parent_id] = []
            # Assuming Notion API returns children in order, or file source maintains order
            blocks_by_parent_id[parent_id].append(block)

    logger.info(f"Processed {len(all_blocks_map)} blocks into maps.")
    spec_blocks_data = []
    
    identified_spec_blocks = []
    for block in all_blocks:
        if block.get("type") == "toggle":
            toggle_title_text = get_block_plain_text(block, params) # Params needed for mentions in title
            if spec_block_identifier in toggle_title_text:
                if 'id' not in block:
                    logger.warning(f"Spec toggle found without ID: '{toggle_title_text}'. Skipping.")
                    continue
                if 'level' not in block:
                    logger.error(f"Spec toggle '{toggle_title_text}' (ID: {block.get('id')}) IS MISSING 'level' attribute. CANNOT PROCESS accurately. Skipping.")
                    continue 
                identified_spec_blocks.append(block)

    if not identified_spec_blocks:
        logger.warning(f"No suitable spec blocks found with identifier '{spec_block_identifier}' and 'level' attribute.")
        return pd.DataFrame(columns=["block_name", "block_content"])

    logger.info(f"Found {len(identified_spec_blocks)} spec blocks to process.")
    for spec_block in identified_spec_blocks:
        spec_block_id = spec_block["id"]
        spec_block_name_full = get_block_plain_text(spec_block, params)
        spec_block_name_clean = spec_block_name_full.replace(spec_block_identifier, "").strip()
        
        spec_block_level_abs = spec_block['level'] # Already checked for existence

        logger.info(f"Processing spec block: '{spec_block_name_clean}' (ID: {spec_block_id}, Level: {spec_block_level_abs})")
        
        # Each spec toggle gets its own traversal context for processed IDs
        processed_ids_for_this_spec_traversal = set()
        
        content_lines = build_spec_content_string_with_quote_logic(
            current_parent_block_id=spec_block_id,
            spec_toggle_absolute_level=spec_block_level_abs,
            all_blocks_map=all_blocks_map,
            blocks_by_parent_id=blocks_by_parent_id,
            params=params,
            processed_block_ids_in_this_traversal=processed_ids_for_this_spec_traversal
        )
        
        full_content_string = "\n".join(content_lines)
        
        spec_blocks_data.append({
            "block_name": spec_block_name_clean,
            "block_content": full_content_string
        })

    if not spec_blocks_data:
        logger.warning("No data generated from spec blocks (e.g., all were empty or only had unprocessed content types).")
        return pd.DataFrame(columns=["block_name", "block_content"])

    try:
        logger.info(f"Writing {len(spec_blocks_data)} spec blocks to CSV: {output_csv_filepath}")
        df = pd.DataFrame(spec_blocks_data, columns=["block_name", "block_content"])
        df.to_csv(output_csv_filepath, index=False, encoding='utf-8')
        logger.info(f"Successfully wrote data to {output_csv_filepath}")
        return df
    except IOError as e:
        logger.error(f"Error writing CSV file: {str(e)}")
        raise # Re-raise to signal failure to caller

def process_spec_blocks(block_identifier:str, page_id: str, table_page_id: str, notion_client: Client):
    logger.info(f"Initiating spec block processing for page: {page_id}, using table: {table_page_id}")
    INPUT_TEXT_FILE = f"blocks/{page_id}_all_blocks.txt" # Consider making dir configurable
    OUTPUT_CSV_FILE = f"{page_id}_spec_block_contents.csv" # Consider making dir configurable

    logger.info("Attempting to extract table data from Notion for parameter resolution.")
    params = {}
    if table_page_id and notion_client: # Only attempt if table_page_id and client are provided
        try:
            params = extract_table_data(table_page_id, notion_client)
            logger.info(f"Successfully extracted {len(params)} parameters from table {table_page_id}.")
        except Exception as e: # Catch a broad exception if extract_table_data fails
            logger.error(f"Failed to extract table data from Notion page {table_page_id}: {e}. Proceeding with empty params.")
            params = {} # Ensure params is an empty dict if fetching fails
    else:
        logger.warning("No table_page_id or notion_client provided for parameter extraction. Proceeding with empty params.")


    df = process_notion_blocks_from_file(
        INPUT_TEXT_FILE,
        OUTPUT_CSV_FILE,
        block_identifier,
        params
    )
    logger.info(f"Spec block processing finished. Returning DataFrame with {len(df if df is not None else [])} rows.")
    return df