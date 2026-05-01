import json
import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

load_dotenv()

class AutoGrader:
    def __init__(self):
        # We use a temperature of 0.0 because grading must be strictly objective, not creative.
        self.llm = ChatGroq(temperature=0.0, model_name="llama-3.1-8b-instant")
        self.parser = JsonOutputParser()

    def grade_short_answer(self, student_answer, ideal_answer, keywords):
        print(f"\n[AUTO-GRADER] Evaluating Student Answer...")
        
        template = """
        You are a strict, objective science examiner grading a short answer question.
        
        Ideal Answer: {ideal_answer}
        Required Keywords: {keywords}
        Student's Answer: {student_answer}
        
        EVALUATION RULES:
        1. Context is King: Does the student's answer demonstrate actual understanding of the concept?
        2. Spelling Leniency: If the student misspells keywords (e.g., "turbin" instead of "turbine"), treat it as a correct keyword match.
        3. Catch Cheaters: If the student merely lists the keywords without forming a logical, scientifically accurate sentence, penalize them heavily.
        
        Calculate a final accuracy score from 0.0 (completely wrong) to 1.0 (perfect).
        
        OUTPUT FORMAT (Return ONLY valid JSON):
        {{
            "accuracy_score": 0.85,
            "feedback": "A short, one-sentence explanation of why they received this score."
        }}
        """
        prompt = PromptTemplate.from_template(template)
        chain = prompt | self.llm | self.parser
        
        try:
            result = chain.invoke({
                "ideal_answer": ideal_answer,
                "keywords": keywords,
                "student_answer": student_answer
            })
            
            print(f" -> Final Accuracy Score: {result['accuracy_score'] * 100:.1f}%")
            print(f" -> AI Feedback: {result['feedback']}\n")
            
            return result['accuracy_score']
            
        except Exception as e:
            print(f" -> Grading failed. Error: {e}")
            return 0.0

if __name__ == "__main__":
    grader = AutoGrader()
    
    ideal = "Electricity is generated in a hydropower station through the conversion of kinetic energy from flowing water into electrical energy. The key component involved in this process is a turbine, which is driven by the flowing water and generates mechanical energy that is then converted into electrical energy by a generator."
    keywords = ["hydropower", "turbine", "generator", "kinetic energy"]
    
    print("\n--- TEST 1: Good Idea, Bad Spelling ---")
    student_1 = "The water uses kinetic energy to spin a turbin which powers a genrator to make hydropower."
    print(f"Student wrote: '{student_1}'")
    grader.grade_short_answer(student_1, ideal, keywords)
    
    print("--- TEST 2: The Cheater (Only keywords, wrong idea) ---")
    student_2 = "hydropower turbine generator kinetic energy but electricity is made by magic."
    print(f"Student wrote: '{student_2}'")
    grader.grade_short_answer(student_2, ideal, keywords)