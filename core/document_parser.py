import fitz  # PyMuPDF
import os
import base64
from typing import List, Dict, Any, Tuple
from PIL import Image
import io
from langchain_core.messages import HumanMessage
from langchain_openai import AzureChatOpenAI

class DocumentParser:
    def __init__(self, config, image_output_dir: str = "output/images"):
        self.image_output_dir = image_output_dir
        self.config = config
        if not os.path.exists(self.image_output_dir):
            os.makedirs(self.image_output_dir)
        
        # Initialize the LLM for image summarization using Azure
        if not all([config.azure_openai_api_key, config.azure_openai_endpoint, config.azure_openai_chat_deployment_name]):
             raise ValueError("Azure OpenAI credentials for Chat are not fully configured for DocumentParser.")
        
        self.llm = AzureChatOpenAI(
            azure_endpoint=config.azure_openai_endpoint,
            api_key=config.azure_openai_api_key,
            api_version=config.azure_openai_api_version,
            azure_deployment=config.azure_openai_chat_deployment_name,
            temperature=0.1, # Lower temperature for more factual summaries
            max_tokens=512
        )

    def parse_pdf(self, file_path: str) -> Dict[str, List[Any]]:
        """
        Parses a PDF file to extract text, images, and tables.
        
        Returns:
            A dictionary containing lists of extracted elements:
            - "texts": List of (text_content, metadata)
            - "images": List of (image_path, metadata)
            - "tables": List of (table_data, metadata)
        """
        doc = fitz.open(file_path)
        
        extracted_elements = {
            "texts": [],
            "images": [],
            "tables": []
        }
        
        base_filename = os.path.splitext(os.path.basename(file_path))[0]

        for page_num, page in enumerate(doc):
            # 1. Extract text blocks
            text_blocks = page.get_text("blocks")
            for i, block in enumerate(text_blocks):
                text = block[4]
                metadata = {
                    "source": file_path,
                    "page_number": page_num + 1,
                    "type": "text",
                    "block_number": i
                }
                extracted_elements["texts"].append((text, metadata))

            # 2. Extract images
            image_list = page.get_images(full=True)
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                
                image_filename = f"{base_filename}_p{page_num+1}_img{img_index}.png"
                image_path = os.path.join(self.image_output_dir, image_filename)
                
                with open(image_path, "wb") as img_file:
                    img_file.write(image_bytes)
                
                metadata = {
                    "source": file_path,
                    "page_number": page_num + 1,
                    "type": "image",
                    "image_path": image_path
                }
                extracted_elements["images"].append((image_path, metadata))

            # 3. Extract tables
            tabs = page.find_tables()
            for i, tab in enumerate(tabs):
                # This gives a list of lists (rows and cells)
                table_data = tab.extract()
                metadata = {
                    "source": file_path,
                    "page_number": page_num + 1,
                    "type": "table",
                    "table_number": i
                }
                extracted_elements["tables"].append((table_data, metadata))

        doc.close()
        return extracted_elements

    def summarize_image(self, image_path: str) -> str:
        """
        Generates a summary for an image using a multi-modal LLM.
        """
        try:
            with open(image_path, "rb") as image_file:
                image_base64 = base64.b64encode(image_file.read()).decode('utf-8')

            message = HumanMessage(
                content=[
                    {"type": "text", "text": "この画像について、内容を詳細に説明してください。グラフであれば、その傾向や読み取れる重要な数値を具体的に記述してください。図であれば、その構造や要素間の関係性を説明してください。"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}",
                            "detail": "high"
                        }
                    },
                ]
            )
            
            response = self.llm.invoke([message])
            return response.content
        except Exception as e:
            print(f"Error summarizing image {image_path}: {e}")
            return "画像の内容を要約できませんでした。"

    def format_table_as_markdown(self, table_data: List[List[str]]) -> str:
        """
        Formats a list of lists representing a table into a Markdown string.
        """
        if not table_data:
            return ""

        # Helper to clean up cell content
        def clean_cell(cell):
            if cell is None:
                return ""
            return str(cell).replace("\n", " ").strip()

        header = "| " + " | ".join(map(clean_cell, table_data[0])) + " |"
        separator = "| " + " | ".join(["---"] * len(table_data[0])) + " |"
        body = "\n".join([
            "| " + " | ".join(map(clean_cell, row)) + " |"
            for row in table_data[1:]
        ])
        
        return f"{header}\n{separator}\n{body}"
