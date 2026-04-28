import os
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings, HuggingFaceEndpoint
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. Load the secret API keys (Groq and Hugging Face)
load_dotenv()

CHROMA_DB_DIR = "data/chroma_db"

def generate_mcq(topic):
    print(f"\n1. Searching database for: '{topic}'...")

    # Load the math model and connect to local database
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vectorstore = Chroma(persist_directory=CHROMA_DB_DIR, embedding_function=embeddings)
    
    # Search for the textbook passages
    results = vectorstore.similarity_search(topic, k=2)
    context = "\n\n".join([doc.page_content for doc in results])
    print("✅ Context found!\n")

    print("2. Connecting to LLM (Primary: Groq, Fallback: Hugging Face)...")

    # The prompt template works for both AI models
    template = """
    You are an expert science teacher. Based ONLY on the following text, write one multiple choice question.
    Include the question, 4 options (A, B, C, D), and clearly state the correct answer.

    Text:
    {context}

    Question:
    """
    prompt = PromptTemplate.from_template(template)
    
    # StrOutputParser ensures the output looks clean regardless of which AI generated it
    output_parser = StrOutputParser()
    
    try:
        # --- PRIMARY: GROQ (Llama 3) ---
        print("   -> Attempting fast generation with Groq...")
        llm = ChatGroq(
            temperature=0.3, 
            model_name="llama-3.1-8b-instant" 
        )
        chain = prompt | llm | output_parser
        response = chain.invoke({"topic": topic, "context": context})
        
    except Exception as e:
        # --- FALLBACK: HUGGING FACE (FLAN-T5) ---
        print(f"   -> Groq attempt failed. Falling back to Hugging Face...")
        llm = HuggingFaceEndpoint(
            repo_id="google/flan-t5-large",
            task="text2text-generation",
            temperature=0.3,
            max_new_tokens=250
        )
        chain = prompt | llm | output_parser
        response = chain.invoke({"topic": topic, "context": context})

    print("\n" + "="*40)
    print("✨ GENERATED QUESTION ✨")
    print("="*40)
    print(response.strip())
    print("="*40 + "\n")

if __name__ == "__main__":
    generate_mcq("Climatic Changes and Temperature")