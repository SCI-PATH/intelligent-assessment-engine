# SCI-PATH Component 2: Dynamic Assessment Engine

## Architecture Overview & Justification
This component is a Python FastAPI microservice that utilizes a combination of **Item Response Theory (IRT)** and a **Reinforcement Learning (PPO)** agent to drive a Retrieval-Augmented Generation (RAG) pipeline.
* **We DO NOT use BKT.** This component handles real-time (micro-adaptive) session flow, leaving long-term knowledge tracking to Component 4.

## The AI Logic (Viva Defense)
1. **IRT (The Baseline):** We use Item Response Theory to handle cold-start calibration. It calculates the initial difficulty starting point.
2. **Reinforcement Learning (The Brain):** A PPO agent acts as the decision-maker. It observes the `State` (Student Accuracy, Response Time). 
    * *Why RL is required:* The agent's `Action Space` is multi-dimensional. It doesn't just output a Difficulty Level (1-10); it also outputs the optimal **Question Type** (e.g., switching from Short Answer to MCQ if the student is highly frustrated). A rule-based system cannot optimize two continuous parameters simultaneously over a 20-minute session.
3. **RAG Pipeline (The Generator):** LangChain pulls context from ChromaDB (Grade 6 Science text) and instructs the LLM to generate the exact Question Type and Difficulty prescribed by the RL agent.

## Implementation Phases
* [ ] Phase 1: Local Setup, API integration, and ChromaDB vector ingestion.
* [ ] Phase 2: Build the RAG generation prompt.
* [ ] Phase 3: Train the RL Gymnasium environment using synthetic student simulations.
* [ ] Phase 4: Expose FastAPI endpoints to the frontend.