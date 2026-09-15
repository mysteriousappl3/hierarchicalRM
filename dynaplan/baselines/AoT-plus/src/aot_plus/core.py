"""Core implementation of the Algorithm of Thoughts Plus (AoT+) methodology."""
from typing import Dict, List, Optional, Any, Callable, Tuple
import re

from src.models.llm_client import LLMClient, get_llm_client

class AoTPlusPromptBuilder:
    """Builder for AoT+ style prompts with state memoization and random trajectory augmentation."""
    
    def __init__(self, domain_description: str):
        """Initialize the AoT+ prompt builder.
        
        Args:
            domain_description: Description of the planning domain (e.g., Blocksworld rules)
        """
        self.domain_description = domain_description
        self.examples = []
        self.state_memoization_interval = 3  # Number of steps between state memoizations
    
    def add_example(self, initial_state: str, goal_state: str, solution_trajectory: List[str], 
                   random_trajectories: List[List[str]]) -> None:
        """Add a few-shot example with both successful and random trajectories.
        
        Args:
            initial_state: Description of initial state
            goal_state: Description of goal state
            solution_trajectory: List of steps in the successful solution path
            random_trajectories: List of lists, where each inner list is a sequence of steps in a failed path
        """
        self.examples.append({
            "initial_state": initial_state,
            "goal_state": goal_state,
            "solution_trajectory": solution_trajectory,
            "random_trajectories": random_trajectories
        })
    
    def _format_state_memoization(self, state_id: str, state_description: str) -> str:
        """Format a state memoization entry.
        
        Args:
            state_id: Identifier for the state (e.g., "1.2.3")
            state_description: Description of the current state
            
        Returns:
            Formatted state memoization string
        """
        return f"STATE {state_id}: {state_description}\n"
    
    def _interleave_trajectories(self, solution: List[str], random_paths: List[List[str]]) -> List[str]:
        """Interleave the solution and random trajectories for example generation.
        
        Args:
            solution: List of steps in the successful solution path
            random_paths: List of lists, where each inner list is a sequence of steps in a random path
            
        Returns:
            List of interleaved steps, showing exploration and backtracking
        """
        # Simple interleaving strategy - can be made more sophisticated
        interleaved = []
        solution_steps_used = 0
        
        # Add initial solution steps (up to half)
        mid_point = len(solution) // 2
        interleaved.extend(solution[:mid_point])
        solution_steps_used = mid_point
        
        # Add random exploration paths with backtracking
        for random_path in random_paths:
            interleaved.append("Let's try a different approach.")
            interleaved.extend(random_path)
            interleaved.append("This approach isn't working well. Let's backtrack.")
        
        # Complete with the rest of the solution
        interleaved.extend(solution[solution_steps_used:])
        
        return interleaved
    
    def _format_example(self, example: Dict[str, Any]) -> str:
        """Format a complete example with state memoization and interleaved trajectories.
        
        Args:
            example: Dictionary containing the example data
            
        Returns:
            Formatted example as a string
        """
        initial_state = example["initial_state"]
        goal_state = example["goal_state"]
        
        # Interleave solution and random trajectories
        steps = self._interleave_trajectories(
            example["solution_trajectory"], 
            example["random_trajectories"]
        )
        
        # Build the example with state memoization
        result = f"Initial state: {initial_state}\n"
        result += f"Goal state: {goal_state}\n\n"
        result += self._format_state_memoization("1.0", initial_state)
        result += "I'll solve this step by step:\n\n"
        
        current_state = initial_state
        plan_steps = []
        
        for i, step in enumerate(steps):
            if "backtrack" not in step.lower() and "approach" not in step.lower():
                # This is an actual action step
                result += f"ACTION: {step}\n"
                plan_steps.append(step)
            else:
                # This is a commentary or backtracking step
                result += f"{step}\n"
            
            # Add state memoization periodically
            if (i+1) % self.state_memoization_interval == 0:
                # If backtracking, use a different state id format
                if "backtrack" in step.lower():
                    state_id = f"{(i+1)//self.state_memoization_interval}.0"
                else:
                    state_id = f"{(i+1)//self.state_memoization_interval+1}.0"
                
                # This would be replaced with actual state computation
                current_state = f"Updated state after step {i+1}"
                result += self._format_state_memoization(state_id, current_state)
        
        result += f"\nFinal check: {goal_state} has been achieved.\n\n"
        
        # Add a plan summary section
        result += "Plan summary:\n"
        for i, step in enumerate(plan_steps):
            result += f"{i+1}. {step}\n"
            
        return result
    
    def build_prompt(self, initial_state: str, goal_state: str) -> str:
        """Build the complete AoT+ prompt for the given problem.
        
        Args:
            initial_state: Description of the initial state for the problem to solve
            goal_state: Description of the goal state for the problem to solve
            
        Returns:
            Complete prompt string
        """
        prompt = f"""# Algorithm of Thoughts Plus (AoT+) Planning System

## Domain Description:
{self.domain_description}

## Planning Task:
Given an initial state and a goal state, create a plan to transform the initial state into the goal state.
Use the Algorithm of Thoughts Plus approach to solve this planning problem.

### Key Instructions:
1. Think step by step to explore possible actions
2. Periodically track and restate the current state (using STATE notation)
3. Explore different paths when needed
4. Backtrack if a path doesn't seem promising
5. Build towards the goal state systematically
6. For each action you take, start the line with "ACTION:" followed by the action description
7. After each action, show the new state using "STATE x.y:" notation
8. Conclude with a "Plan summary:" section that lists all the actions in numbered format

## Examples:
"""
        # Add formatted examples
        for example in self.examples:
            prompt += f"{self._format_example(example)}\n---\n\n"
        
        # Add the actual problem to solve
        prompt += f"""## Problem to Solve:

Initial state: {initial_state}
Goal state: {goal_state}

STATE 0: {initial_state}

Solve this step by step, tracking the state periodically. Remember to:
1. Prefix each action with "ACTION:" 
2. Update the state after significant changes using "STATE x.y:" notation
3. End with a "Plan summary:" section

Start your solution:
"""
        return prompt


class AoTPlus:
    """Main implementation of Algorithm of Thoughts Plus."""
    
    def __init__(self, domain_description: str, llm_provider: Optional[str] = None):
        """Initialize the AoT+ implementation.
        
        Args:
            domain_description: Description of the planning domain (e.g., Blocksworld rules)
            llm_provider: Optional LLM provider to use. If None, uses the first available provider.
        """
        self.llm_client = get_llm_client(llm_provider)
        self.prompt_builder = AoTPlusPromptBuilder(domain_description)
        
    def add_example(self, initial_state: str, goal_state: str, solution_trajectory: List[str], 
                   random_trajectories: List[List[str]]) -> None:
        """Add a few-shot example to the prompt builder."""
        self.prompt_builder.add_example(
            initial_state, goal_state, solution_trajectory, random_trajectories
        )
        
    def solve(self, initial_state: str, goal_state: str, 
              temperature: float = 0.0, max_tokens: int = 3000) -> str:
        """Solve a planning problem using AoT+.
        
        Args:
            initial_state: Description of the initial state
            goal_state: Description of the goal state
            temperature: Sampling temperature for the LLM
            max_tokens: Maximum number of tokens to generate
            
        Returns:
            The generated solution plan
        """
        prompt = self.prompt_builder.build_prompt(initial_state, goal_state)
        return self.llm_client.generate(prompt, temperature, max_tokens)
    
    def extract_plan(self, solution_text: str) -> List[str]:
        """Extract the final plan steps from the solution text.
        
        Args:
            solution_text: The raw output from the LLM
            
        Returns:
            List of plan steps
        """
        steps = []
        
        # First try to extract from "Plan summary:" section
        plan_summary_pattern = r"[Pp]lan [Ss]ummary:?(.*?)(?=$|\n\n)"
        plan_summary_match = re.search(plan_summary_pattern, solution_text, re.DOTALL)
        
        if plan_summary_match:
            # Extract steps from numbered list in plan summary
            plan_summary = plan_summary_match.group(1)
            numbered_step_pattern = r"(\d+)[\.:\)]\s+(.*?)(?=\n\d+[\.:\)]|\Z)"
            for match in re.finditer(numbered_step_pattern, plan_summary, re.DOTALL):
                step = match.group(2).strip()
                if step:
                    steps.append(step)
        
        # If no steps found from plan summary, look for ACTION: format
        if not steps:
            action_pattern = r"ACTION:\s*(.*?)(?=STATE|ACTION|\n\n|$)"
            action_matches = re.finditer(action_pattern, solution_text)
            for match in action_matches:
                action = match.group(1).strip()
                if action and not action.lower().startswith("no action"):
                    steps.append(action)
        
        # If still no steps found, try Step format
        if not steps:
            step_pattern = r"Step (\d+):\s*(.*?)(?=Step \d+:|$)"
            step_matches = re.finditer(step_pattern, solution_text, re.DOTALL)
            for match in step_matches:
                step = match.group(2).strip()
                if step and not any(x in step.lower() for x in ["let's try", "approach isn't", "backtrack"]):
                    steps.append(step)
        
        # If still no steps found, look for numbered actions outside of plan summary
        if not steps:
            # First check for a list of actions with ordinal numbers
            action_list_pattern = r"(?:^|\n)(\d+)[\.:\)]\s+(.*?)(?=\n\d+[\.:\)]|\Z)"
            for match in re.finditer(action_list_pattern, solution_text, re.DOTALL):
                step = match.group(2).strip()
                if step and not any(x in step.lower() for x in ["let's try", "approach isn't", "backtrack"]):
                    steps.append(step)
        
        return steps 