"""Simple demonstration of AoT+ methodology."""
from src.aot_plus.core import AoTPlus
from src.domains.blocksworld import BlocksWorldDomain
from src.domains.logistics import LogisticsDomain
from src.models.llm_client import get_llm_client

def demonstrate_blocksworld():
    """Demonstrate AoT+ on a Blocksworld problem."""
    print("=== Demonstrating AoT+ on Blocksworld ===")
    
    # Get domain description and example problem
    domain_description = BlocksWorldDomain.get_domain_description()
    initial_state, goal_state, solution_trajectory, random_trajectories = BlocksWorldDomain.generate_example_problem()
    
    # Create Azure OpenAI client
    azure_client = get_llm_client("azure_openai")
    
    # Build the AoT+ prompt
    print("\nBuilding AoT+ prompt...")
    aot = AoTPlus(domain_description, "azure_openai")
    aot.llm_client = azure_client  # Override the LLM client
    aot.add_example(initial_state, goal_state, solution_trajectory, random_trajectories)
    
    # Generate solution
    print("\nGenerating solution using Azure OpenAI...")
    solution_text = aot.solve(initial_state, goal_state)
    
    # Extract plan steps
    print("\nExtracting plan steps...")
    plan_steps = aot.extract_plan(solution_text)
    
    # Print results
    print("\nProblem:")
    print(f"Initial State: {initial_state}")
    print(f"Goal State: {goal_state}")
    
    print("\nExtracted Plan:")
    for i, step in enumerate(plan_steps):
        print(f"{i+1}. {step}")
    
    return solution_text


def demonstrate_logistics():
    """Demonstrate AoT+ on a Logistics problem."""
    print("\n=== Demonstrating AoT+ on Logistics ===")
    
    # Get domain description and example problem
    domain_description = LogisticsDomain.get_domain_description()
    initial_state, goal_state, solution_trajectory, random_trajectories = LogisticsDomain.generate_example_problem()
    
    # Create Azure OpenAI client
    azure_client = get_llm_client("azure_openai")
    
    # Build the AoT+ prompt
    print("\nBuilding AoT+ prompt...")
    aot = AoTPlus(domain_description, "azure_openai")
    aot.llm_client = azure_client  # Override the LLM client
    aot.add_example(initial_state, goal_state, solution_trajectory, random_trajectories)
    
    # Generate solution
    print("\nGenerating solution using Azure OpenAI...")
    solution_text = aot.solve(initial_state, goal_state)
    
    # Extract plan steps
    print("\nExtracting plan steps...")
    plan_steps = aot.extract_plan(solution_text)
    
    # Print results
    print("\nProblem:")
    print(f"Initial State: {initial_state}")
    print(f"Goal State: {goal_state}")
    
    print("\nExtracted Plan:")
    for i, step in enumerate(plan_steps):
        print(f"{i+1}. {step}")
    
    return solution_text


def print_key_aspects(blocksworld_solution, logistics_solution):
    """Print the key aspects of AoT+ methodology."""
    print("\n=== Key Aspects of AoT+ Methodology ===")
    
    print("\n1. Periodic State Memoization:")
    # Extract and print some STATE examples from the solutions
    state_examples = []
    for line in blocksworld_solution.split("\n"):
        if line.startswith("STATE"):
            state_examples.append(line.strip())
            if len(state_examples) >= 3:
                break
    
    print("\n   Examples from Blocksworld solution:")
    for example in state_examples:
        print(f"   - {example}")
    
    print("\n   Purpose:")
    print("   - These state markers help the LLM keep track of the current state")
    print("   - Reduces 'state hallucination' where the LLM loses track of the world state")
    print("   - Works like a form of memoization, reducing cognitive load")
    
    print("\n2. Random Trajectory Augmentation:")
    # Extract examples of exploration and backtracking
    exploration_examples = []
    for line in logistics_solution.split("\n"):
        if "approach" in line.lower() or "backtrack" in line.lower():
            exploration_examples.append(line.strip())
            if len(exploration_examples) >= 3:
                break
    
    print("\n   Examples from Logistics solution:")
    for example in exploration_examples:
        print(f"   - {example}")
    
    print("\n   Purpose:")
    print("   - Demonstrates the search process, including exploration and backtracking")
    print("   - Teaches the LLM to try different approaches and recover from failures")
    print("   - Simplifies prompt engineering compared to manually crafting search heuristics")
    
    print("\nThese aspects together enable LLMs to solve complex planning problems autonomously.")
    print("For more details, refer to the paper: 'LLMs CAN PLAN ONLY IF WE TELL THEM'")


if __name__ == "__main__":
    # Demonstrate on Blocksworld
    blocks_solution = demonstrate_blocksworld()
    
    # Demonstrate on Logistics
    logistics_solution = demonstrate_logistics()
    
    # Show the key aspects of AoT+
    print_key_aspects(blocks_solution, logistics_solution) 