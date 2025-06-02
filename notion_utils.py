from typing import List, Dict, Any, Tuple
import urllib.parse

def get_all_page_content(
    start_block_id: str,
    notion_client: Any,
    _spec_block_name: str = "💡TECHNICAL_FUNCTION_VALUE:"
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """
    function to fetch all blocks from a start_block_id (e.g., page_id)
    and identify "technical function value" toggles with their children.

    Args:
        start_block_id: The ID of the block (often a page ID) to start traversal from.
        notion_client: The initialized Notion client.

    Returns:
        A tuple containing:
        - all_blocks (List[Dict[str, Any]]): A list of all block objects found,
          excluding 'ai_block' types.
          This list does NOT include the start_block_id block itself, only its descendants.
        - tech_specs (Dict[str, List[Dict[str, Any]]]): A dictionary where keys are
          the IDs of "technical function value" toggle blocks, and values are lists
          of their direct children (excluding 'ai_block' types).
    """
    all_blocks: List[Dict[str, Any]] = []
    tech_specs: Dict[str, List[Dict[str, Any]]] = {}

    # First, handle the start_block_id itself for potential tech_spec,
    # as the recursive helper will only process children.
    try:
        # print(f"DEBUG: Retrieving start_block_id: {start_block_id}")
        root_block = notion_client.blocks.retrieve(block_id=start_block_id)
        # print(f"DEBUG: Retrieved root_block: {root_block.get('type')}, has_children: {root_block.get('has_children')}")
        _check_and_add_spec(root_block, tech_specs, notion_client, _spec_block_name)
    except Exception as e:
        print(f"Error fetching or processing start_block {start_block_id}: {e}")
        # Decide if you want to return early or continue if children might still be accessible
        # For now, let's assume if the root fails, we can't proceed well.
        return all_blocks, tech_specs

    # If the start_block_id itself has children, begin recursive fetching for them.
    # The children of start_block_id will be at level 0.
    if root_block.get("has_children", False):
        # print(f"DEBUG: Start_block_id {start_block_id} has children, starting recursive fetch.")
        _fetch_children_recursively(
            parent_block_id=start_block_id,
            level=0,
            all_blocks_accumulator=all_blocks,
            tech_specs_accumulator=tech_specs,
            notion_client=notion_client,
            _spec_block_name=_spec_block_name
        )
    else:
        # print(f"DEBUG: Start_block_id {start_block_id} has no children.")
        pass

    return all_blocks, tech_specs


def _check_and_add_spec(
    block: Dict[str, Any],
    tech_specs_accumulator: Dict[str, List[Dict[str, Any]]],
    notion_client: Any,
    _spec_block_name: str
):
    """
    Checks if a given block is a "_spec_block_name" toggle and, if so,
    fetches its children and adds them to the tech_specs_accumulator.
    """
    block_type = block.get("type")
    if block_type == "toggle":
        toggle_content = block.get("toggle", {}).get("rich_text", [])
        if toggle_content and toggle_content[0].get("type") == "text":
            text_content = toggle_content[0].get("text", {}).get("content", "")
            if _spec_block_name in text_content:
                if block.get("has_children", False):
                    block_id = block["id"]
                    # print(f"DEBUG: Found tech spec toggle: {block_id}")
                    try:
                        children_response = notion_client.blocks.children.list(block_id=block_id)
                        tech_spec_children = [
                            child for child in children_response.get("results", [])
                            if child.get("type") != "ai_block"
                        ]
                        tech_specs_accumulator[block_id] = tech_spec_children
                        # print(f"DEBUG: Added {len(tech_spec_children)} children for tech_spec {block_id}")
                    except Exception as e:
                        print(f"Error fetching children for tech_spec toggle {block_id}: {e}")


def _fetch_children_recursively(
    parent_block_id: str,
    level: int,
    all_blocks_accumulator: List[Dict[str, Any]],
    tech_specs_accumulator: Dict[str, List[Dict[str, Any]]],
    notion_client: Any,
    _spec_block_name: str
):
    """
    Recursively fetches children of a block, populates all_blocks_accumulator,
    and identifies tech_spec toggles to populate tech_specs_accumulator.
    """
    # print(f"DEBUG: Fetching children for {parent_block_id} at level {level}")
    try:
        children_response = notion_client.blocks.children.list(block_id=parent_block_id)
    except Exception as e:
        print(f"Error fetching children of block {parent_block_id}: {e}")
        return

    for child_block in children_response.get("results", []):
        if child_block.get("type") == "ai_block":
            continue

        child_block["level"] = level
        all_blocks_accumulator.append(child_block)

        # Check if this child_block is a tech_spec toggle
        _check_and_add_spec(child_block, tech_specs_accumulator, notion_client, _spec_block_name)

        # If this child block itself has children, recurse
        if child_block.get("has_children", False):
            _fetch_children_recursively(
                parent_block_id=child_block["id"],
                level=level + 1,
                all_blocks_accumulator=all_blocks_accumulator,
                tech_specs_accumulator=tech_specs_accumulator,
                notion_client=notion_client,
                _spec_block_name=_spec_block_name
            )

def get_children_with_parent_id(parent_id, all_blocks):
  blocks = []
  for block in all_blocks:
    if block["parent"].get("block_id", "") == parent_id:
      blocks.append(block)
  return blocks

def extract_table_data(
    page_id: str,
    notion_client: Any
) -> dict: 
    
    all_database_pages = []
    start_cursor=None
    print(f"Querying database with ID: {page_id}")

    while True:
        response = notion_client.databases.query(
            database_id=page_id,
            start_cursor=start_cursor
        )

        all_database_pages.extend(response['results'])

        if response.get('has_more'):
            start_cursor = response.get('next_cursor')
            # print(f"Found more results. Fetching next batch from cursor: {start_cursor}")
        else:
            break # No more results to fetch

        print(f"\nSuccessfully retrieved {len(all_database_pages)} entries from the database.")

    processed_data = {}

    for page in all_database_pages: # Iterate through each page
        extracted_row = {}

        # Extract Page ID from URL
        page_url = page.get("url")
        if page_url:
            parsed_url = urllib.parse.urlparse(page_url)
            path_segments = parsed_url.path.split('/')
            if path_segments and '-' in path_segments[-1]:
                # The last segment typically contains "page_slug-page_id_without_dashes"
                row_page_id = path_segments[-1].split('-')[-1]
            else:
                row_page_id = page['id'].replace('-', '') # Fallback to page['id'] without dashes
        else:
            row_page_id = None

        # Iterate through the properties of the current page (row)
        properties = page.get("properties", {})

        # Mapping for easier access
        desired_properties = {
            "API Link": "rich_text",
            "API Parameter Name": "rich_text",
            "Business Description": "rich_text",
            "ERP Link": "url",
            "Name": "title"
        }

        for prop_name, _ in desired_properties.items():
            prop_data = properties.get(prop_name)
            value = None # Default to None if property is missing or empty

            if prop_data:
                actual_type = prop_data.get('type')

                if actual_type == 'title' and prop_data['title']:
                    value = "".join([t['plain_text'] for t in prop_data['title']])
                elif actual_type == 'rich_text' and prop_data['rich_text']:
                    value = "".join([t['plain_text'] for t in prop_data['rich_text']])
                elif actual_type == 'url':
                    value = prop_data['url']
            
            extracted_row[prop_name] = value

        processed_data[row_page_id] = extracted_row
    
    return processed_data