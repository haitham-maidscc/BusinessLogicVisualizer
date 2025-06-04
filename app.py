import streamlit as st
import pandas as pd
import os
import subprocess
import tempfile
from notion_client import Client as NotionClient
from dotenv import load_dotenv, find_dotenv
from parse_spec_block import process_spec_blocks
from b2m_agent import build_mermaid_agent, run_agent, run_agent
from notion_utils import get_all_page_content
from streamlit_mermaid import st_mermaid
from langchain.chat_models import init_chat_model

load_dotenv(find_dotenv(), override=True)

import warnings
# Ignore all warnings
warnings.filterwarnings("ignore")

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

APP_ROOT = os.path.dirname(os.path.abspath(__file__)) # Root directory of your Streamlit app
NODE_MODULES_DIR = os.path.join(APP_ROOT, "node_modules")
PACKAGE_JSON_PATH = os.path.join(APP_ROOT, "package.json")

st.info("🔧 Running npm install...")

# Command to run.
# If you have package.json:
# command = ["npm", "install", "--prefix", APP_ROOT, "--cache", os.path.join(APP_ROOT, ".npm-cache")]
# If you want to install a specific package without package.json (less recommended):
command = ["npm", "install", "@mermaid-js/mermaid-cli", "--prefix", APP_ROOT, "--cache", os.path.join(APP_ROOT, ".npm-cache")]

process = subprocess.run(
    command,
    cwd=APP_ROOT,  # Run in the app's root directory
    capture_output=True,
    text=True,
    check=True  # Raise an exception for non-zero exit codes
)
st.success("✅ npm install completed successfully!")
if process.stdout:
    # st.text_area("npm install stdout:", process.stdout, height=100)
    print(f"NPM Install STDOUT: {process.stdout}") # Logs to Streamlit Cloud logs
if process.stderr:
    # st.text_area("npm install stderr:", process.stderr, height=100)
    print(f"NPM Install STDERR: {process.stderr}") # Logs to Streamlit Cloud logs

logger.info("Starting application initialization")
logger.info("Libraries imported successfully")

# --- LLM Setup ---
MODEL_GEMINI_2_0_FLASH = "gemini-2.0-flash"
GEMINI_MODEL = "gemini-2.5-flash-preview-05-20"
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
logger.info(f"Initializing chat model with {ANTHROPIC_MODEL}")
llm = init_chat_model(f"anthropic:{ANTHROPIC_MODEL}")

# Table mapping configuration
TABLE_MAPPING = {
    "MV_Resolvers": "1eb7432eb8438080b80bf2483e27b9b9",
    "Doctors": "1ed7432eb843809f912fdbb4c370998e"
}

NOTION_TOKEN = os.environ.get("NOTION_SECRET")
if not NOTION_TOKEN:
    logger.error("NOTION_SECRET environment variable not found")
    raise ValueError("NOTION_SECRET environment variable is required")
notion_client = NotionClient(auth=NOTION_TOKEN)
logger.info("Environment configured successfully")

def fetch_data_spec_content(block_identifier: str, page_id: str, table_id: str, notion: NotionClient) -> pd.DataFrame:
    logger.info(f"Fetching data spec content for block: {block_identifier}, page: {page_id}, table: {table_id}")
    
    block_file_path = f"blocks/{page_id}_all_blocks.txt"
    if not os.path.exists(block_file_path):
        logger.info("Loading blocks from Notion API")
        all_blocks_data, _ = get_all_page_content(page_id, notion, _spec_block_name=block_identifier)
        try:
            with open(block_file_path, "w", encoding="utf-8") as f:
                f.write(str(all_blocks_data))
            logger.info(f"Successfully saved blocks to {block_file_path}")
        except Exception as e:
            logger.error(f"Error saving blocks to file: {str(e)}")
            raise

    return process_spec_blocks(block_identifier, page_id, table_id, notion)

def process_dataframe_with_mermaid_agent(page_id: str, df: pd.DataFrame, logic_column: str = "original_logic", max_retries: int = 3) -> pd.DataFrame:
    """
    Takes a DataFrame and applies the agent to each row, using the value in `logic_column` as the business logic.
    Returns the DataFrame with a new column 'mermaid_graph' containing the generated Mermaid code (or None if failed).
    """
    logger.info(f"Processing dataframe with mermaid agent for page: {page_id}")
    graph_file_path = f"graphs/{page_id}_graphs.csv"

    if not os.path.exists(graph_file_path):
        logger.info("Building mermaid agent")
        app = build_mermaid_agent()

        def process_row(row):
            logic = row[logic_column]
            if pd.isna(logic) or not str(logic).strip():
                logger.debug(f"Skipping empty logic for row: {row.name}")
                return None
            logger.debug(f"Processing logic for row: {row.name}")
            return run_agent(app, llm, str(logic), max_retries=max_retries)

        df = df.copy()
        logger.info("Applying mermaid agent to dataframe rows")
        df["mermaid_graph"] = df.apply(process_row, axis=1)
        try:
            df.to_csv(graph_file_path, index=False)
            logger.info(f"Successfully saved graphs to {graph_file_path}")
        except Exception as e:
            logger.error(f"Error saving graphs to file: {str(e)}")
            raise
    else:
        logger.info(f"Loading existing graphs from {graph_file_path}")
        df = pd.read_csv(graph_file_path)

    return df

def generate_svg_from_mermaid_code(mermaid_code: str, theme: str = "default", background: str = "transparent") -> str | None:
    """
    Generates SVG content from Mermaid code using the mmdc CLI.
    Returns the SVG string or None if an error occurs.
    """
    logger.info("Generating SVG from Mermaid code")
    try:
        # Clean up the Mermaid code
        mermaid_code = mermaid_code.strip()
        if mermaid_code.startswith("```mermaid"):
            mermaid_code = mermaid_code[len("```mermaid"):]
        if mermaid_code.endswith("```"):
            mermaid_code = mermaid_code[:-len("```")]
        mermaid_code = mermaid_code.strip()

        # Create temporary files for input and output
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".mmd") as tmp_input_file:
            tmp_input_file.write(mermaid_code)
            input_file_path = tmp_input_file.name

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".svg") as tmp_output_file:
            output_file_path = tmp_output_file.name

        # Construct the mmdc command
        command = [
            "mmdc",
            "-i", input_file_path,
            "-o", output_file_path,
            "-t", theme,
            "-b", background
        ]

        logger.debug(f"Running mmdc command: {' '.join(command)}")
        process = subprocess.run(command, capture_output=True, text=True)

        if process.returncode == 0 and os.path.exists(output_file_path):
            with open(output_file_path, "r", encoding="utf-8") as f:
                svg_content = f.read()
            logger.info("Successfully generated SVG")
            return svg_content
        else:
            logger.error(f"Mermaid CLI failed to generate SVG. Stderr: {process.stderr}")
            if process.stdout:
                logger.error(f"MMDC Stdout: {process.stdout}")
            return None

    except FileNotFoundError:
        logger.error("Mermaid CLI (mmdc) not found")
        st.error(
            "Mermaid CLI (mmdc) not found. "
            "Please install it: `npm install -g @mermaid-js/mermaid-cli` "
            "and ensure it's in your system's PATH."
        )
        return None
    except Exception as e:
        logger.error(f"Error generating SVG: {str(e)}")
        st.error(f"An unexpected error occurred while generating SVG: {e}")
        return None
    finally:
        # Clean up temporary files
        if 'input_file_path' in locals() and os.path.exists(input_file_path):
            os.remove(input_file_path)
        if 'output_file_path' in locals() and os.path.exists(output_file_path):
            os.remove(output_file_path)

def create_zip_of_svgs(df: pd.DataFrame, theme: str = "default", background: str = "transparent") -> tuple[bytes, str]:
    """
    Create a zip file containing all SVGs from the DataFrame
    Returns a tuple of (zip_bytes, error_message)
    """
    logger.info("Creating zip file of SVGs")
    import zipfile
    from io import BytesIO
    
    memory_file = BytesIO()
    error_messages = []
    
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for _, row in df.iterrows():
            try:
                svg_content = generate_svg_from_mermaid_code(
                    row['mermaid_graph'],
                    theme=theme,
                    background=background
                )
                if svg_content:
                    filename = f"{row['block_name'].replace('/', '_')}.svg"
                    zipf.writestr(filename, svg_content)
                else:
                    error_messages.append(f"Failed to generate SVG for {row['block_name']}")
            except Exception as e:
                logger.error(f"Error processing SVG for {row['block_name']}: {str(e)}")
                error_messages.append(f"Error processing {row['block_name']}: {str(e)}")
                continue
    
    memory_file.seek(0)
    error_message = "\n".join(error_messages) if error_messages else None
    return memory_file.getvalue(), error_message

# --- Streamlit App UI ---
logger.info("Initializing Streamlit UI")
st.set_page_config(layout="wide")
st.title("📄 Business Flowchart Generator")

# Initialize session state for storing results if they don't exist
if 'agent_result_df' not in st.session_state:
    st.session_state.agent_result_df = None
if 'download_filename' not in st.session_state:
    st.session_state.download_filename = "data.csv"

# --- Sidebar for Agent Selection and Inputs ---
st.sidebar.header("⚙️ Agent Configuration")

# Documentation section
with st.sidebar.expander("📖 How to use this tool"):
    st.markdown("""
    This tool helps you generate business flowcharts from Notion pages. Here's what you need to provide:
    
    - **Block Identifier**: The name of the code block in Notion that contains your business logic
    - **Page ID**: The unique identifier of your Notion page (found in the page URL)
    - **Table**: Select the relevant table from the dropdown list
    
    **Tips:**
    - Page IDs can be found in the URL of your Notion page
    - Make sure your Notion page has the correct permissions set
    - The block identifier should match exactly with the code block name in your Notion page
    """)

# Input fields with tooltips
block_identifier = st.sidebar.text_input(
    "Enter Block identifier:",
    key="agent3_block_title",
    help="The name of the code block in Notion that contains your business logic. This should match exactly with the code block name in your Notion page."
)

page_id_input = st.sidebar.text_input(
    "Enter Page ID:",
    key="agent3_page_id",
    help="The unique identifier of your Notion page. You can find this in the page URL after 'notion.so/' and before any '?' or '#'. Example: '1234567890abcdef'"
)

# Replace text input with dropdown for table selection
selected_table_name = st.sidebar.selectbox(
    "Select Table:",
    options=list(TABLE_MAPPING.keys()),
    key="agent3_table_selection",
    help="Select the relevant table from the list. This will automatically use the correct table ID."
)

# Button to trigger agent execution
if st.sidebar.button("🚀 Run Agent", key="run_agent_button"):
    logger.info("Agent execution triggered")
    st.session_state.agent_result_df = None # Reset previous results

    if page_id_input and selected_table_name:
        try:
            table_id = TABLE_MAPPING[selected_table_name]
            logger.info(f"Processing request for Block: {block_identifier}, Page: {page_id_input}, Table: {selected_table_name} (ID: {table_id})")
            with st.spinner(f"Processing for Identifier: {block_identifier}, Page ID: {page_id_input}, Table: {selected_table_name}..."):
                df_result = fetch_data_spec_content(block_identifier, page_id_input, table_id, notion_client)
            st.session_state.agent_result_df = df_result
            st.session_state.download_filename = f"{block_identifier}_{page_id_input}_table_{selected_table_name}.csv"

            with st.spinner("Generating Mermaid Graph..."):
                logger.info("Starting mermaid graph generation")
                df_result = process_dataframe_with_mermaid_agent(page_id_input, df_result, logic_column="block_content", max_retries=3)
                st.session_state.agent_result_df = df_result
                st.session_state.download_filename = f"mermaid_graph_{page_id_input}_table_{selected_table_name}.csv"
                logger.info("Mermaid graph generation completed successfully")
                st.sidebar.success("Mermaid Graph generated successfully!")
            
        except Exception as e:
            logger.error(f"Error in Agent execution: {str(e)}", exc_info=True)
            st.sidebar.error(f"Error in Agent: {str(e)}")

# --- Main Area for Displaying Results ---
if st.session_state.agent_result_df is not None:
    logger.info("Displaying results in main area")
    st.subheader("📊 Mermaid Graph Viewer")
    
    # Add theme selection
    theme = st.sidebar.selectbox(
        "Select Theme",
        options=["default", "forest", "dark", "neutral"],
        help="Choose a theme for the Mermaid diagrams"
    )
    
    # Create a dropdown with block names
    block_names = st.session_state.agent_result_df['block_name'].tolist()
    selected_block = st.selectbox("Select a graph to view:", block_names)
    logger.debug(f"Selected block: {selected_block}")
    
    # Get the corresponding Mermaid code
    selected_row = st.session_state.agent_result_df[st.session_state.agent_result_df['block_name'] == selected_block].iloc[0]
    mermaid_code = selected_row['mermaid_graph']
    
    # Clean up the Mermaid code
    mermaid_code = mermaid_code.strip()
    if mermaid_code.startswith("```mermaid"):
        mermaid_code = mermaid_code[len("```mermaid"):]
    if mermaid_code.endswith("```"):
        mermaid_code = mermaid_code[:-len("```")]
    mermaid_code = mermaid_code.strip()
    
    # Display the graph
    try:
        logger.info(f"Rendering mermaid graph for block: {selected_block}")
        st_mermaid(mermaid_code, height=600)

        # Add download buttons in a horizontal layout
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("Prepare SVG for Download", key="prepare_svg"):
                with st.spinner("Generating SVG..."):
                    svg_content = generate_svg_from_mermaid_code(
                        mermaid_code,
                        theme=theme,
                        background="transparent"
                    )
                
                if svg_content:
                    st.success("SVG generated successfully!")
                    st.download_button(
                        label="Download SVG",
                        data=svg_content,
                        file_name=f"{selected_block.replace('/', '_')}.svg",
                        mime="image/svg+xml",
                        key="download_single_svg"
                    )
                else:
                    st.error("Could not generate SVG for download.")

        with col2:
            if st.button("Prepare All SVGs (ZIP)", key="prepare_all_svgs"):
                with st.spinner("Generating ZIP file with all SVGs..."):
                    zip_bytes, error_message = create_zip_of_svgs(
                        st.session_state.agent_result_df,
                        theme=theme,
                        background="transparent"
                    )
                    
                    if zip_bytes:
                        st.success("ZIP file generated successfully!")
                        if error_message:
                            st.warning("Some SVGs could not be generated. See details below.")
                            with st.expander("Error Details"):
                                st.text(error_message)
                        
                        st.download_button(
                            label="Download All SVGs (ZIP)",
                            data=zip_bytes,
                            file_name=f"all_graphs_{page_id_input}.zip",
                            mime="application/zip",
                            key="download_all_svgs"
                        )
                    else:
                        st.error("Could not generate ZIP file.")

        st.subheader("📊 CSV Data Sample (First 5 Rows)")
        st.dataframe(st.session_state.agent_result_df.head())

        # Convert DataFrame to CSV string for download
        csv_string = st.session_state.agent_result_df.to_csv(index=False).encode('utf-8')
        logger.info("Preparing CSV download")

        st.download_button(
            label="📥 Download Full CSV",
            data=csv_string,
            file_name=st.session_state.download_filename,
            mime='text/csv',
            key='download_button'
        )
    except Exception as e:
        logger.error(f"Error rendering Mermaid graph: {str(e)}", exc_info=True)
        st.error(f"Error rendering Mermaid graph: {str(e)}")
        st.text("Raw Mermaid code:")
        st.code(mermaid_code, language="mermaid")

st.markdown("---")
st.caption("A simple agent data extraction app.")
logger.info("Application initialization completed")