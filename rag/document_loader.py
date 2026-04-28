import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

# 1. Define where our files live
PDF_PATH = "data/grade_6_science.pdf"
CHROMA_DB_DIR = "data/chroma_db"

def ingest_pdf():
    print(f"Loading PDF from {PDF_PATH}...")
    # 2. Load the PDF
    loader = PyPDFLoader(PDF_PATH)
    documents = loader.load()

    print("Splitting text into chunks...")
    # 3. Cut the book into smaller paragraphs so the AI can read it easily
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = text_splitter.split_documents(documents)

    print(f"Created {len(chunks)} chunks. Initializing embedding model...")
    # 4. Use the free, local sentence-transformers to convert text to math
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    print("Saving chunks to local ChromaDB. This might take a minute...")
    # 5. Save everything into the local database folder
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_DB_DIR
    )

    print("✅ Database successfully built and saved!")

if __name__ == "__main__":
    ingest_pdf()