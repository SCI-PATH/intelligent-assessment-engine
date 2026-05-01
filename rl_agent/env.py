import gymnasium as gym
from gymnasium import spaces
import numpy as np
import math

class StudentEnv(gym.Env):
    """
    RESEARCH GRADE VIRTUAL CLASSROOM
    Utilizes Item Response Theory (IRT) and Multi-Factor Observations.
    """
    def __init__(self):
        super(StudentEnv, self).__init__()
        
        # ACTION SPACE: 0 = Decrease, 1 = Keep Same, 2 = Increase
        self.action_space = spaces.Discrete(3)
        
        # OBSERVATION SPACE: [Proficiency, Time_Taken, Last_Correct, Streak]
        # All values normalized between 0.0 and 1.0 for the Neural Network
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(4,), dtype=np.float32)
        
        # Initial rules
        self.current_proficiency = 0.5
        self.time_taken = 0.5
        self.last_correct = 0.0
        self.streak = 0.0
        
        self.current_difficulty = 5 
        self.steps = 0
        self.max_steps = 10 

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_proficiency = 0.5
        self.time_taken = 0.0
        self.last_correct = 0.0
        self.streak = 0.0
        self.current_difficulty = 5
        self.steps = 0
        
        return self._get_obs(), {}

    def _get_obs(self):
        """Helper function to return the 4-factor observation array."""
        return np.array([
            self.current_proficiency, 
            self.time_taken, 
            self.last_correct, 
            self.streak
        ], dtype=np.float32)

    def step(self, action):
        self.steps += 1
        
        # 1. Apply AI's Action
        if action == 0:
            self.current_difficulty = max(1, self.current_difficulty - 1)
        elif action == 2:
            self.current_difficulty = min(10, self.current_difficulty + 1)
            
        # 2. ITEM RESPONSE THEORY (IRT) SIMULATION
        # Convert proficiency (0 to 1) and difficulty (1 to 10) to an IRT scale (-3 to +3)
        theta_ability = (self.current_proficiency * 6) - 3
        b_difficulty = ((self.current_difficulty / 10) * 6) - 3
        
        # The Rasch Model Formula: Probability of getting the question right
        probability_correct = 1.0 / (1.0 + math.exp(-(theta_ability - b_difficulty)))
        
        # Simulate the student answering based on that probability
        is_correct = 1 if np.random.rand() < probability_correct else 0
        self.last_correct = float(is_correct)
        
        # Simulate time taken (Harder questions take more time, mapped 0 to 1)
        base_time = 0.2 + (self.current_difficulty * 0.05)
        self.time_taken = min(1.0, base_time + np.random.uniform(-0.1, 0.1))
        
        # Update streak and proficiency
        if is_correct:
            self.streak = min(1.0, self.streak + 0.2)
            self.current_proficiency = min(1.0, self.current_proficiency + 0.05)
        else:
            self.streak = 0.0
            self.current_proficiency = max(0.0, self.current_proficiency - 0.05)
            
        # 3. REWARD CALCULATION (Zone of Proximal Development)
        # We want the probability of them getting it right to be around 50-70%.
        # If it's 99% (too easy) or 10% (too hard), penalize the AI.
        if 0.4 <= probability_correct <= 0.75:
            reward = 1.0  # Perfect difficulty!
        elif probability_correct > 0.75:
            reward = -0.5 # Too easy, student is bored
        else:
            reward = -1.0 # Too hard, student is frustrated
            
        terminated = bool(self.steps >= self.max_steps)
        truncated = False
        
        return self._get_obs(), float(reward), terminated, truncated, {}

if __name__ == "__main__":
    env = StudentEnv()
    obs, info = env.reset()
    print("✅ Research-Grade Virtual Classroom Initialized!")
    print(f"Initial Obs [Proficiency, Time, Correct, Streak]: {obs}")
    
    # Test one step
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    print(f"\nAI chose action: {action}")
    print(f"New Obs: {obs}")
    print(f"Reward: {reward}")