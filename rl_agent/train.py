import os
from stable_baselines3 import PPO
from rl_agent.env import StudentEnv

def train_agent():
    print("\n1. Initializing the Virtual Classroom...")
    env = StudentEnv()

    print("2. Creating the AI Brain (PPO Algorithm)...")
    # MlpPolicy means it uses a standard, lightweight Neural Network.
    # verbose=1 tells it to print out its progress while training.
    model = PPO("MlpPolicy", env, verbose=1)

    print("3. Training the AI on 20,000 simulated student interactions...")
    # Because there are no humans involved, the computer can simulate
    # 20,000 quizzes in just a few seconds!
    model.learn(total_timesteps=20000)

    print("\n4. Training complete! Saving the AI's brain...")
    # Create a folder called 'models' in your main directory to store the brain
    os.makedirs("models", exist_ok=True)
    model.save("models/ppo_student_agent")
    
    print("✅ Brain successfully saved to models/ppo_student_agent.zip!")

if __name__ == "__main__":
    train_agent()