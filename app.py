import streamlit as st
import pandas as pd
import os
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

import logging
logging.basicConfig(level=logging.ERROR)
print("Libraries imported.")

# --- LLM Setup ---
MODEL_GEMINI_2_0_FLASH = "gemini-2.0-flash"
GEMINI_MODEL = "gemini-2.5-flash-preview-05-20"
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
llm = init_chat_model(f"anthropic:{ANTHROPIC_MODEL}")

NOTION_TOKEN = os.environ.get("NOTION_SECRET")
notion_client = NotionClient(auth=NOTION_TOKEN)
print("\nEnvironment configured.")

def fetch_data_spec_content(block_identifier: str, page_id: str, table_id: str, notion: NotionClient) -> pd.DataFrame:

    if not os.path.exists(f"blocks/{page_id}_all_blocks.txt"):
        print("loading blocks from notion API")
        all_blocks_data, _ = get_all_page_content(page_id, notion, _spec_block_name=block_identifier)
        with open(f"blocks/{page_id}_all_blocks.txt", "w", encoding="utf-8") as f:
            f.write(str(all_blocks_data))

    return process_spec_blocks(block_identifier, page_id, table_id, notion)

def process_dataframe_with_mermaid_agent(page_id: str, df: pd.DataFrame, logic_column: str = "original_logic", max_retries: int = 3) -> pd.DataFrame:
    """
    Takes a DataFrame and applies the agent to each row, using the value in `logic_column` as the business logic.
    Returns the DataFrame with a new column 'mermaid_graph' containing the generated Mermaid code (or None if failed).
    """
    if not os.path.exists(f"graphs/{page_id}_graphs.csv"):

        app = build_mermaid_agent()

        def process_row(row):
            logic = row[logic_column]
            # If logic is NaN or empty, skip
            if pd.isna(logic) or not str(logic).strip():
                return None
            return run_agent(app, llm, str(logic), max_retries=max_retries)

        df = df.copy()
        df["mermaid_graph"] = df.apply(process_row, axis=1)
        df.to_csv(f"graphs/{page_id}_graphs.csv", index=False)
    else:
        df = pd.read_csv(f"graphs/{page_id}_graphs.csv")

    return df

# --- Streamlit App UI ---

st.set_page_config(layout="wide")
st.title("📄 Business Flowchart Generator")

# Initialize session state for storing results if they don't exist
if 'agent_result_df' not in st.session_state:
    st.session_state.agent_result_df = None
if 'download_filename' not in st.session_state:
    st.session_state.download_filename = "data.csv"

# --- Sidebar for Agent Selection and Inputs ---
st.sidebar.header("⚙️ Agent Configuration")

# Input fields - these will be dynamically shown based on agent selection
page_id_input = ""
table_id_input = ""

block_identifier = st.sidebar.text_input("Enter Block identifier:", key="agent3_block_title")
page_id_input = st.sidebar.text_input("Enter Page ID:", key="agent3_page_id")
table_id_input = st.sidebar.text_input("Enter Table ID:", key="agent3_table_id")

# Button to trigger agent execution
if st.sidebar.button("🚀 Run Agent", key="run_agent_button"):
    st.session_state.agent_result_df = None # Reset previous results

    if page_id_input and table_id_input:
        try:
            with st.spinner(f"Processing for Identifier: {block_identifier}, Page ID: {page_id_input}, Table ID: {table_id_input}..."):
                df_result = fetch_data_spec_content(block_identifier, page_id_input, table_id_input, notion_client)
            st.session_state.agent_result_df = df_result
            st.session_state.download_filename = f"{block_identifier}_{page_id_input}_table_{table_id_input}.csv"

            with st.spinner("Generating Mermaid Graph..."):
                df_result = process_dataframe_with_mermaid_agent(page_id_input, df_result, logic_column="block_content", max_retries=3)
                st.session_state.agent_result_df = df_result
                st.session_state.download_filename = f"mermaid_graph_{page_id_input}_table_{table_id_input}.csv"
                st.sidebar.success("Mermaid Graph generated successfully!")
            
        except Exception as e:
            st.sidebar.error(f"Error in Agent: {str(e)}")

# --- Main Area for Displaying Results ---
if st.session_state.agent_result_df is not None:
    st.subheader("📊 Mermaid Graph Viewer")
    
    # Create a dropdown with block names
    block_names = st.session_state.agent_result_df['block_name'].tolist()
    selected_block = st.selectbox("Select a graph to view:", block_names)
    
    # Get the corresponding Mermaid code
    selected_row = st.session_state.agent_result_df[st.session_state.agent_result_df['block_name'] == selected_block].iloc[0]
    mermaid_code = selected_row['mermaid_graph']
    
    # Clean up the Mermaid code (remove markdown backticks if present)
    mermaid_code = mermaid_code.strip()
    if mermaid_code.startswith("```mermaid"):
        mermaid_code = mermaid_code[len("```mermaid"):]
    if mermaid_code.endswith("```"):
        mermaid_code = mermaid_code[:-len("```")]
    mermaid_code = mermaid_code.strip()
    
    # Display the graph
    try:
        st_mermaid(mermaid_code, height=600)

        st.subheader("📊 CSV Data Sample (First 5 Rows)")
        st.dataframe(st.session_state.agent_result_df.head())

        # Convert DataFrame to CSV string for download
        csv_string = st.session_state.agent_result_df.to_csv(index=False).encode('utf-8')

        st.download_button(
            label="📥 Download Full CSV",
            data=csv_string,
            file_name=st.session_state.download_filename,
            mime='text/csv',
            key='download_button'
        )
    except Exception as e:
        st.error(f"Error rendering Mermaid graph: {str(e)}")
        st.text("Raw Mermaid code:")
        st.code(mermaid_code, language="mermaid")
        

st.markdown("---")
st.caption("A simple agent data extraction app.")