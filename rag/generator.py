import os
import json
import random
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings, HuggingFaceEndpoint
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

load_dotenv()

CHROMA_DB_DIR = "data/chroma_db"

# [INTEGRATION PLACEHOLDER]: Currently randomly selecting from local array. 
# Post-integration, this variable will be populated by an active JSON payload from Component 1.
MOCK_TOPICS = [
    "Photosynthesis", 
    "The Water Cycle", 
    "Types of Mixtures", 
    "Static Electricity",
    "Climatic Changes and Temperature"
]

def generate_question(difficulty=5, question_type="MCQ"):
    topic = random.choice(MOCK_TOPICS)
    print(f"\n[INTEGRATION MOCK] Component 1 supplied topic: '{topic}'")
    print(f"1. Searching database for: '{topic}'...")

    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vectorstore = Chroma(persist_directory=CHROMA_DB_DIR, embedding_function=embeddings)
    
    results = vectorstore.similarity_search(topic, k=2)
    context = "\n\n".join([doc.page_content for doc in results])
    print("✅ Context found!\n")

    print(f"2. Connecting to LLM... (Type: {question_type}, Target Difficulty: {difficulty}/10)")

    template = """
    You are an expert science teacher. Based ONLY on the following text, write one {question_type} question.
    
    CRITICAL INSTRUCTION: The difficulty must be exactly level {difficulty} out of 10.
    
    FORMAT INSTRUCTIONS:
    You MUST return ONLY a valid JSON object. Do not include markdown blocks or extra text.
    
    If question_type is "MCQ":
    {{
        "question": "The question text",
        "options": {{
            "A": "Correct answer",
            "B": "Wrong answer 1",
            "C": "Wrong answer 2",
            "D": "Wrong answer 3"
        }},
        "correct_answer": "A",
        "tags": {{
            "B": "NEAR_MISS",
            "C": "MISCONCEPTION",
            "D": "COMPLETE_MISS"
        }}
    }}
    
    If question_type is "True/False":
    {{
        "question": "The statement to evaluate",
        "correct_answer": "True" (or "False")
    }}
    
    If question_type is "Fill-in-the-Blank":
    {{
        "question": "The sentence with a ____ representing the missing word.",
        "correct_answer": "The missing word"
    }}
    
    If question_type is "Short Answer":
    {{
        "question": "The open-ended question prompt.",
        "ideal_answer": "A perfect, complete sentence answering the question.",
        "keywords": ["keyword1", "keyword2", "keyword3"] 
    }}

    Text:
    {context}
    """
    prompt = PromptTemplate.from_template(template)
    output_parser = JsonOutputParser()
    
    try:
        llm = ChatGroq(
            temperature=0.3, 
            model_name="llama-3.1-8b-instant"
        )
        chain = prompt | llm | output_parser
        response = chain.invoke({
            "topic": topic, 
            "context": context, 
            "difficulty": difficulty,
            "question_type": question_type
        })
        
    except Exception as e:
        print(f"   -> Groq error or JSON parsing failed. Error: {e}")
        return None

    print("\n" + "="*50)
    print(f"✨ GENERATED {question_type.upper()} QUESTION ✨")
    print("="*50)
    print(json.dumps(response, indent=4))
    print("="*50 + "\n")
    
    return response

if __name__ == "__main__":
    # Let's test the brand new Short Answer format!
    print("\n--- TESTING SHORT ANSWER ---")
    generate_question(difficulty=7, question_type="Short Answer")