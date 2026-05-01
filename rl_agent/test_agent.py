from stable_baselines3 import PPO
from rl_agent.env import StudentEnv

def test_trained_agent():
    print("1. Loading Virtual Classroom...")
    env = StudentEnv()
    
    print("2. Waking up the trained AI Brain...")
    # Load the zip file we just created!
    model = PPO.load("models/ppo_student_agent")
    
    obs, info = env.reset()
    print(f"\n🎓 New Student Entered. Starting Proficiency: {obs[0]:.2f}")
    
    # Let's watch the AI make 5 decisions in a row
    for step in range(5):
        # The AI looks at the student's proficiency and predicts the best action
        action, _states = model.predict(obs, deterministic=True)
        
        # We apply that action to the classroom
        obs, reward, terminated, truncated, info = env.step(action.item())
        
        # Translate the number into English for us to read
        action_name = ["Make Easier", "Keep Same", "Make Harder"][action.item()]
        
        print(f"Question {step+1}: AI chose to '{action_name}' | Student Proficiency became: {obs[0]:.2f} | Reward: {reward}")

if __name__ == "__main__":
    test_trained_agent()