from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
from rag.generator import generate_question

# Initialize the API Server
app = FastAPI(title="SCI-PATH Dynamic Assessment Engine API")

# --- DATA CONTRACTS (Pydantic Models) ---

# [INTEGRATION PLACEHOLDER]: This is the exact schema Component 1 will send us
class Component1Payload(BaseModel):
    topic: str
    subtopic_id: str
    text_content: str

# [INTEGRATION PLACEHOLDER]: This is the exact schema we will send to Component 4
class Component4Response(BaseModel):
    topic_id: str
    question_type: str
    difficulty_level: int
    question_data: dict

# --- API ENDPOINTS ---

@app.post("/generate_assessment", response_model=Component4Response)
def generate_assessment_endpoint(payload: Component1Payload):
    print(f"\n[API ROUTER] Received payload from Component 1: Topic - {payload.topic}")
    
    # In the future, we will ingest payload.text_content directly. 
    # For now, we trigger our pipeline which uses the mock topics and ChromaDB.
    target_difficulty = 6 # This will eventually come from the RL Agent
    q_type = "MCQ"
    
    generated_json = generate_question(difficulty=target_difficulty, question_type=q_type)
    
    # Construct the exact payload Component 4 expects
    response_payload = Component4Response(
        topic_id=payload.topic,
        question_type=q_type,
        difficulty_level=target_difficulty,
        question_data=generated_json
    )
    
    return response_payload

@app.get("/")
def health_check():
    return {"status": "Assessment Engine API is running"}

if __name__ == "__main__":
    # Runs the server on localhost port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)