from stable_baselines3 import PPO
from rl_agent.env import StudentEnv
from rag.generator import generate_mcq

def run_intelligent_assessment(topic="Climatic Changes and Temperature"):
    print("="*60)
    print("🚀 INTELLIGENT ASSESSMENT ENGINE - FULL PIPELINE TEST 🚀")
    print("="*60)
    
    # --- PART 1: THE RL MANAGER ---
    print("\n[MANAGER] Loading Virtual Classroom & PPO Brain...")
    env = StudentEnv()
    model = PPO.load("models/ppo_student_agent")
    
    # Simulate a new student entering the system
    obs, info = env.reset()
    current_proficiency = obs[0]
    
    print(f"[MANAGER] New student detected. Current Proficiency: {current_proficiency:.2f} / 1.00")
    
    # The AI Brain looks at the proficiency and decides the next move
    action, _states = model.predict(obs, deterministic=True)
    action_name = ["Make Easier", "Keep Same", "Make Harder"][action.item()]
    
    # We apply that action to the environment to calculate the exact difficulty number (1-10)
    obs, reward, terminated, truncated, info = env.step(action.item())
    target_difficulty = env.unwrapped.current_difficulty
    
    print(f"[MANAGER] Decision: '{action_name}'. Setting Target Difficulty to: {target_difficulty}/10")
    
    # --- PART 2: THE RAG WRITER ---
    print("\n[WRITER] Receiving instructions from Manager...")
    print(f"[WRITER] Generating a Level {target_difficulty} question about '{topic}'...")
    
    # The Handshake! We pass the RL Agent's chosen difficulty directly into our LangChain/Groq pipeline
    generate_mcq(topic, difficulty=target_difficulty)

if __name__ == "__main__":
    run_intelligent_assessment()