"""Main application entry point for the AoT+ implementation."""
import argparse
import sys
from typing import Optional

from src.aot_plus.core import AoTPlus
from src.domains.blocksworld import BlocksWorldDomain
from src.domains.logistics import LogisticsDomain
from src.utils.config import Config

def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="AoT+ Planning System")
    parser.add_argument("--domain", type=str, default="blocksworld", 
                        choices=["blocksworld", "logistics"], help="Planning domain to use")
    parser.add_argument("--provider", type=str, default=None,
                        choices=["azure_openai", "openai", "anthropic", "google"], 
                        help="LLM provider to use")
    parser.add_argument("--initial", type=str, required=False,
                        help="Initial state description (default: use example problem)")
    parser.add_argument("--goal", type=str, required=False,
                        help="Goal state description (default: use example problem)")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="Sampling temperature for the LLM")
    return parser.parse_args()

def main():
    """Main application entry point."""
    args = parse_args()
    
    # Check if there's any provider available
    available_providers = Config.get_available_providers()
    if not available_providers:
        print("Error: No LLM provider is configured. Please check your .env file.")
        sys.exit(1)
    
    # Set default provider if none specified
    provider = args.provider or Config.get_default_provider()
    
    print(f"Using LLM provider: {provider}")
    
    # Initialize the domain
    if args.domain == "blocksworld":
        domain_description = BlocksWorldDomain.get_domain_description()
        
        # Initialize AoT+ with the domain description
        aot = AoTPlus(domain_description, provider)
        
        # Add example for few-shot prompting
        example = BlocksWorldDomain.generate_example_problem()
        aot.add_example(*example)
        
        # Use provided initial and goal states, or use defaults
        if args.initial and args.goal:
            initial_state = args.initial
            goal_state = args.goal
        else:
            print("Using example problem for demonstration...")
            initial_state, goal_state, _, _ = example
    elif args.domain == "logistics":
        domain_description = LogisticsDomain.get_domain_description()
        
        # Initialize AoT+ with the domain description
        aot = AoTPlus(domain_description, provider)
        
        # Add example for few-shot prompting
        example = LogisticsDomain.generate_example_problem()
        aot.add_example(*example)
        
        # Use provided initial and goal states, or use defaults
        if args.initial and args.goal:
            initial_state = args.initial
            goal_state = args.goal
        else:
            print("Using example problem for demonstration...")
            initial_state, goal_state, _, _ = example
    else:
        print(f"Error: Unsupported domain: {args.domain}")
        sys.exit(1)
    
    print("\nSolving planning problem with AoT+...")
    print(f"Initial state: {initial_state}")
    print(f"Goal state: {goal_state}")
    print("\nGenerating solution...")
    
    # Solve the problem
    solution_text = aot.solve(initial_state, goal_state, args.temperature)
    
    print("\nAoT+ Solution:")
    print("=" * 50)
    print(solution_text)
    print("=" * 50)
    
    # Extract and print just the plan steps
    plan_steps = aot.extract_plan(solution_text)
    print("\nExtracted Plan:")
    for i, step in enumerate(plan_steps):
        print(f"{i+1}. {step}")

if __name__ == "__main__":
    main() 