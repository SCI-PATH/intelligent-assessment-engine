# SCI-PATH Component 2: Dynamic Assessment Engine

## Architecture Overview
This component operates as a Python FastAPI microservice, utilizing **Item Response Theory (IRT)** and a **Reinforcement Learning (PPO)** agent to drive a Retrieval-Augmented Generation (RAG) pipeline. This system governs real-time, micro-adaptive session flow.

## Core System Logic
1. **IRT Calibration:** Employs the Rasch Model (1PL) to calculate probabilistic student outcomes, bridging the gap between student ability and generated question difficulty.
2. **Reinforcement Learning Orchestrator:** A PPO agent processes a 4-factor state array (`Proficiency`, `Time Taken`, `Last Correct`, `Streak`) to calculate the optimal Zone of Proximal Development and dictate the parameters for the next generation cycle.
3. **RAG Pipeline:** Extracts contextual data from the vector database (ChromaDB) to ground the Groq LLM generations, preventing hallucinations.

## Automated Evaluation & Data Contracts
To facilitate seamless integration with external system components, the evaluation module outputs strict schemas:
* **MCQ Evaluation:** Returns binary accuracy and categorizes incorrect responses using Distractor Tags (`NEAR_MISS`, `MISCONCEPTION`, `COMPLETE_MISS`).
* **Short Answer Evaluation:** Utilizes NLP keyword extraction and fuzzy string matching to return a continuous `Similarity Score` (accuracy percentage).

## Implementation Phases
* [x] Phase 1: Local Environment Setup & Vector Ingestion.
* [x] Phase 2: RAG Pipeline Initialization.
* [x] Phase 3: RL Gymnasium Environment Construction.
* [x] Phase 4: Pipeline Orchestration (RL-to-RAG Handshake).
* [x] Phase 5: Advanced IRT & Multi-Factor State Integration.
* [ ] Phase 6: Multi-Modal Question Generation (MCQ with Distractors, T/F, Fill-in-Blanks).
* [ ] Phase 7: Multi-Modal Question Generation (Short Answer & Keyword Schemas).
* [ ] Phase 8: Intelligent Evaluation Module (Fuzzy Matching & Auto-Grading).
* [ ] Phase 9: FastAPI Endpoint Exigency & Component Mocking (Placeholders for Component 1 & 4).
* [ ] Phase 10: Local Diagnostic Dashboard (UI for Quiz runtime, Results breakdown, and RL telemetry).