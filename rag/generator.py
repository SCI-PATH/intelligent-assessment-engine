import os
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings, HuggingFaceEndpoint
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

CHROMA_DB_DIR = "data/chroma_db"

# NOTE: We added 'difficulty' as an argument here!
def generate_mcq(topic, difficulty=5):
    print(f"\n1. Searching database for: '{topic}'...")

    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vectorstore = Chroma(persist_directory=CHROMA_DB_DIR, embedding_function=embeddings)
    
    results = vectorstore.similarity_search(topic, k=2)
    context = "\n\n".join([doc.page_content for doc in results])
    print("✅ Context found!\n")

    print(f"2. Connecting to LLM... (Requested Difficulty: {difficulty}/10)")

    # NOTE: The template now strictly enforces the difficulty level
    template = """
    You are an expert science teacher. Based ONLY on the following text, write one multiple choice question.
    
    CRITICAL INSTRUCTION: The difficulty of this question must be exactly level {difficulty} out of 10.
    - Level 1-3: Very simple recall of basic facts.
    - Level 4-7: Moderate understanding and application.
    - Level 8-10: Highly complex, analytical, requiring deep reasoning.

    Include the question, 4 options (A, B, C, D), and clearly state the correct answer.

    Text:
    {context}

    Question:
    """
    prompt = PromptTemplate.from_template(template)
    output_parser = StrOutputParser()
    
    try:
        llm = ChatGroq(
            temperature=0.4, 
            model_name="llama-3.1-8b-instant"
        )
        chain = prompt | llm | output_parser
        # Pass the difficulty into the chain!
        response = chain.invoke({"topic": topic, "context": context, "difficulty": difficulty})
        
    except Exception as e:
        print(f"   -> Groq attempt failed. Falling back to Hugging Face...")
        llm = HuggingFaceEndpoint(
            repo_id="google/flan-t5-large",
            task="text2text-generation",
            temperature=0.4,
            max_new_tokens=250
        )
        chain = prompt | llm | output_parser
        response = chain.invoke({"topic": topic, "context": context, "difficulty": difficulty})

    print("\n" + "="*50)
    print(f"✨ GENERATED QUESTION (TARGET DIFFICULTY: {difficulty}) ✨")
    print("="*50)
    print(response.strip())
    print("="*50 + "\n")

# Let's test it with a high difficulty!
if __name__ == "__main__":
    generate_mcq("Climatic Changes and Temperature", difficulty=9)