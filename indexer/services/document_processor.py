from __future__ import annotations

from pathlib import Path
from typing import Union, List, Dict, Any, Optional
import base64
import io
import logging
import tempfile
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.chunking import HybridChunker
from docling.document_extractor import DocumentExtractor  # Added for metadata extraction
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.chunker.hierarchical_chunker import (
    DocChunk,
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.serializer.markdown import (
    MarkdownTableSerializer,
    MarkdownParams,
)
from docling_core.types.doc import DoclingDocument
from docling_core.types.doc import TableItem, PictureItem
from docling_core.types.doc.labels import DocItemLabel

from transformers import AutoTokenizer
from sentence_transformers import SentenceTransformer

from indexer.core.config import settings

logger = logging.getLogger(__name__)


class RAGMarkdownSerializerProvider(ChunkingSerializerProvider):
    """
    Serializer for chunking:
    - Renders tables as markdown in the text.
    - Uses a clear image placeholder (%%IMAGE%%) in the text.
    """

    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(
            doc=doc,
            table_serializer=MarkdownTableSerializer(),
            params=MarkdownParams(
                image_placeholder="%%IMAGE%%",
            ),
        )


def _encode_pil_to_base64(img, fmt: str = "PNG") -> str:
    """Encode a PIL image to base64 string (no filesystem touch)."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class DocumentProcessor:
    """Process documents using Docling and generate RAG-ready chunks"""
    
    def __init__(
        self,
        embed_model_id: str = None,
        max_tokens: int = None,
        generate_embeddings: bool = True
    ):
        self.embed_model_id = embed_model_id or settings.embed_model_id
        self.max_tokens = max_tokens or settings.max_tokens
        self.generate_embeddings = generate_embeddings
        
        # Initialize embedding model if needed
        self.embedding_model = None
        if self.generate_embeddings:
            try:
                logger.info(f"Loading embedding model: {self.embed_model_id}")
                self.embedding_model = SentenceTransformer(self.embed_model_id)
                logger.info("Embedding model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load embedding model: {str(e)}")
                self.generate_embeddings = False
    
    def process_document(
        self,
        source: Union[str, Path, bytes],
        file_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Process a document and return structured chunks.
        
        Args:
            source: File path, Path object, or bytes content
            file_name: Original file name (required if source is bytes)
        
        Returns:
            List of chunk dictionaries with text, images, tables, and embeddings
        """
        try:
            # Handle bytes input
            if isinstance(source, bytes):
                if not file_name:
                    raise ValueError("file_name is required when source is bytes")
                
                # Create temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_name).suffix) as tmp_file:
                    tmp_file.write(source)
                    tmp_file_path = tmp_file.name
                
                try:
                    chunks = self._process_file(tmp_file_path, file_name)
                finally:
                    # Clean up temporary file
                    Path(tmp_file_path).unlink(missing_ok=True)
                
                return chunks
            else:
                # Handle file path
                source_str = str(source)
                file_name = file_name or Path(source_str).name
                return self._process_file(source_str, file_name)
                
        except Exception as e:
            logger.error(f"Error processing document: {str(e)}")
            raise
    
    def _process_file(self, file_path: str, file_name: str) -> List[Dict[str, Any]]:
        """Internal method to process a file"""
        file_stem = Path(file_name).stem
        
        # 1) Convert with picture images enabled
        logger.info(f"Converting document: {file_name}")
        pdf_opts = PdfPipelineOptions()
        pdf_opts.generate_page_images = False
        pdf_opts.generate_picture_images = True
        
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts),
            }
        )
        conv_res = converter.convert(file_path)
        dl_doc: DoclingDocument = conv_res.document
        
        logger.info(f"Document converted successfully: {file_name}")
        
        # 2) Build tokenizer aligned to embedding model
        logger.info("Initializing tokenizer and chunker")
        hf_tok = AutoTokenizer.from_pretrained(self.embed_model_id)
        tokenizer = HuggingFaceTokenizer(tokenizer=hf_tok, max_tokens=self.max_tokens)
        
        # 3) Chunk structurally with table-aware markdown serialization
        serializer_provider = RAGMarkdownSerializerProvider()
        chunker = HybridChunker(tokenizer=tokenizer, serializer_provider=serializer_provider)
        
        chunks: List[Dict[str, Any]] = []
        
        logger.info("Starting chunking process")
        for idx, base_chunk in enumerate(chunker.chunk(dl_doc=dl_doc)):
            doc_chunk = DocChunk.model_validate(base_chunk)
            
            # Contextualized text for this chunk
            text = chunker.contextualize(chunk=base_chunk)
            
            images: List[Dict[str, Any]] = []
            tables_markdown: List[Dict[str, str]] = []
            tables_html: List[Dict[str, str]] = []
            
            # Extract images and tables
            for item in doc_chunk.meta.doc_items:
                ref = item.self_ref
                label = item.label
                
                # Pictures -> base64 PNGs in-memory
                if label == DocItemLabel.PICTURE and isinstance(ref, str) and ref.startswith("#/pictures/"):
                    try:
                        pic_index = int(ref.split("/")[-1])
                        picture: PictureItem = dl_doc.pictures[pic_index]
                        pil_image = picture.get_image(doc=dl_doc)
                        if pil_image is not None:
                            b64 = _encode_pil_to_base64(pil_image, fmt="PNG")
                            images.append(
                                {
                                    "self_ref": ref,
                                    "mime_type": "image/png",
                                    "data_base64": b64,
                                }
                            )
                    except Exception as e:
                        logger.warning(f"Failed to process image {ref}: {str(e)}")
                
                # Tables -> DataFrame -> markdown + HTML
                if label == DocItemLabel.TABLE and isinstance(ref, str) and ref.startswith("#/tables/"):
                    try:
                        table_index = int(ref.split("/")[-1])
                        table: TableItem = dl_doc.tables[table_index]
                        df = table.export_to_dataframe()
                        
                        tables_markdown.append(
                            {
                                "self_ref": ref,
                                "markdown": df.to_markdown(index=False),
                            }
                        )
                        tables_html.append(
                            {
                                "self_ref": ref,
                                "html": df.to_html(index=False),
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to process table {ref}: {str(e)}")
            
            # Determine chunk type
            chunk_type = []
            if text and text.strip():
                chunk_type.append("text")
            if images:
                chunk_type.append("image")
            if tables_markdown:
                chunk_type.append("table")
            
            # Generate embedding if enabled
            embedding = None
            if self.generate_embeddings and self.embedding_model and text:
                try:
                    embedding = self.embedding_model.encode(text).tolist()
                except Exception as e:
                    logger.warning(f"Failed to generate embedding for chunk {idx}: {str(e)}")
            
            chunk_dict = {
                "id": f"{file_stem}_chunk_{idx}",
                "text": text,
                "chunk_index": idx,
                "char_count": len(text),
                "type": chunk_type if chunk_type else ["text"],
                "images": images,
                "tables_markdown": tables_markdown,
                "tables_html": tables_html,
                "embedding": embedding,
            }
            
            chunks.append(chunk_dict)
        
        logger.info(f"Chunking completed: {len(chunks)} chunks created")
        return chunks
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for a text"""
        if not self.embedding_model:
            logger.warning("Embedding model not loaded")
            return None
        
        try:
            return self.embedding_model.encode(text).tolist()
        except Exception as e:
            logger.error(f"Error generating embedding: {str(e)}")
            return None

    def extract_metadata(self, source: Union[str, Path], file_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract specific metadata from the document using Docling DocumentExtractor.
        Target fields: case_diary_no, fir_no, ps, date, district
        
        Returns:
            Dictionary with extracted metadata, or empty dict if extraction fails
        """
        try:
            # Set environment variables for Hugging Face to avoid symlinks warning
            import os
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
            os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"

            logger.info(f"Extracting metadata from: {file_name or source}")
            
            # Initialize Extractor
            extractor = DocumentExtractor(allowed_formats=[InputFormat.IMAGE, InputFormat.PDF])
            
            # Template for metadata extraction
            metadata_template = '{"case_diary_no": "string", "fir_no": "float", "ps":"string", "date":"string", "district": "string"}'

            # Extract metadata
            result = extractor.extract(
                source=str(source),  # Ensure string path
                template=metadata_template,
            )
            
            # Process the result - result.pages contains the extracted data
            extracted_data = {}
            
            # Check if result has pages attribute (as shown in user's test code)
            if hasattr(result, 'pages') and result.pages:
                # result.pages is typically a list of page results
                # Aggregate data from all pages or use the first page
                if isinstance(result.pages, list) and len(result.pages) > 0:
                    # Get data from first page (or merge all pages)
                    page_data = result.pages[0]
                    
                    # If page_data is a dict, use it directly
                    if isinstance(page_data, dict):
                        extracted_data = page_data
                    # If page_data has attributes, try to convert to dict
                    elif hasattr(page_data, '__dict__'):
                        extracted_data = page_data.__dict__
                    # If it's a string representation, try to parse
                    elif isinstance(page_data, str):
                        try:
                            import json
                            extracted_data = json.loads(page_data)
                        except:
                            # If not JSON, store as raw string
                            extracted_data = {"raw": page_data}
                else:
                    # If pages is not a list, try to access it directly
                    extracted_data = {"pages": str(result.pages)}
            else:
                # If no pages attribute, try to get data directly from result
                if hasattr(result, '__dict__'):
                    extracted_data = result.__dict__
                else:
                    # Fallback: return string representation
                    extracted_data = {"raw_extraction": str(result)}
            
            logger.info(f"Metadata extracted successfully: {extracted_data}")
            return extracted_data
            
        except Exception as e:
            logger.error(f"Error extracting metadata: {str(e)}", exc_info=True)
            return {}


