"""Blocksworld domain implementation for AoT+ demonstration."""
from typing import Dict, List, Set, Tuple, Optional

class BlocksWorldState:
    """Representation of a state in the Blocksworld domain."""
    
    def __init__(self, blocks: List[str]):
        """Initialize a BlocksWorldState.
        
        Args:
            blocks: List of block names/identifiers
        """
        self.blocks = blocks
        # Dictionary mapping blocks to what they're on (another block or 'table')
        self.on = {block: 'table' for block in blocks}  
        # Set of blocks that have nothing on top of them
        self.clear = set(blocks)
        
    def move(self, block: str, destination: str) -> bool:
        """Move a block to a destination (another block or 'table').
        
        Args:
            block: The block to move
            destination: Where to place the block (another block or 'table')
            
        Returns:
            True if the move was valid and performed, False otherwise
        """
        # Check if move is valid
        if block not in self.clear:
            return False  # Block has something on top of it
            
        if destination != 'table' and destination not in self.blocks:
            return False  # Invalid destination
            
        if destination != 'table' and destination not in self.clear:
            return False  # Destination block has something on top
            
        if destination == block:
            return False  # Can't put a block on itself
        
        # Update the state
        current_location = self.on[block]
        
        # If block was on another block, that block is now clear
        if current_location != 'table':
            self.clear.add(current_location)
            
        # Update location of the moved block
        self.on[block] = destination
        
        # If moved to another block, that block is no longer clear
        if destination != 'table':
            self.clear.remove(destination)
            
        return True
        
    def __str__(self) -> str:
        """Convert the state to a readable string representation.
        
        Returns:
            String representation of the state
        """
        result = []
        for block in self.blocks:
            result.append(f"Block {block} is on {self.on[block]}")
        
        return ", ".join(result)
    
    def is_goal_state(self, goal_state: 'BlocksWorldState') -> bool:
        """Check if this state matches the goal state.
        
        Args:
            goal_state: The goal state to compare against
            
        Returns:
            True if this state matches the goal state, False otherwise
        """
        return all(self.on[block] == goal_state.on[block] for block in self.blocks)


class BlocksWorldDomain:
    """Implementation of the Blocksworld planning domain."""
    
    @staticmethod
    def get_domain_description() -> str:
        """Get the description of the Blocksworld domain for the prompt.
        
        Returns:
            Domain description string
        """
        return """
# Blocksworld Planning Domain

## Description:
Blocksworld is a planning domain that involves stacking and unstacking blocks. 
The world consists of a set of blocks and a table. Blocks can be stacked on top of each other or placed on the table.

## Rules:
1. A block can be moved if and only if it has nothing on top of it (it is "clear").
2. A block can be placed on top of another block only if that other block has nothing on top of it.
3. Any number of blocks can be placed directly on the table.
4. The goal is typically to transform an initial configuration of blocks into a target configuration.

## Actions:
The only action in this domain is to move a block from its current position (on the table or on another block) 
to a new position (on the table or on a different block).

## Action Format:
- Move block X from its current position to the top of block Y
- Move block X from its current position to the table

## State Representation:
The state of the world is represented by describing which block is on top of which other block or the table.
For example: "Block A is on the table, Block B is on Block A, Block C is on the table"
"""

    @staticmethod
    def parse_state_description(description: str) -> BlocksWorldState:
        """Parse a natural language description of a Blocksworld state.
        
        Args:
            description: Natural language description of the state
            
        Returns:
            BlocksWorldState object representing the described state
        """
        # Extract block names from the description
        block_pattern = r"Block ([A-Za-z0-9]+)"
        import re
        blocks = set(re.findall(block_pattern, description))
        
        # Create state with all blocks initially on the table
        state = BlocksWorldState(list(blocks))
        
        # Parse the "on" relationships
        on_pattern = r"Block ([A-Za-z0-9]+) is on ([A-Za-z0-9]+|table)"
        for match in re.finditer(on_pattern, description):
            block = match.group(1)
            destination = match.group(2)
            
            # Update the state
            if destination != "table":
                # Remove both blocks from clear set temporarily
                if block in state.clear:
                    state.clear.remove(block)
                if destination in state.clear:
                    state.clear.remove(destination)
                
                # Set the on relationship
                state.on[block] = destination
                
                # Add only the top block back to clear set
                state.clear.add(block)
            else:
                state.on[block] = "table"
                state.clear.add(block)
                
        return state
    
    @staticmethod
    def generate_example_problem() -> Tuple[str, str, List[str], List[List[str]]]:
        """Generate an example Blocksworld problem with solution and random trajectories.
        
        Returns:
            Tuple of (initial_state_description, goal_state_description, 
                     solution_trajectory, random_trajectories)
        """
        initial_state = "Block A is on the table, Block B is on Block A, Block C is on the table"
        goal_state = "Block A is on Block B, Block B is on Block C, Block C is on the table"
        
        solution = [
            "Move Block B from Block A to the table",
            "Move Block A from the table to Block C",
            "Move Block B from the table to Block A"
        ]
        
        random_trajectory1 = [
            "Move Block B from Block A to the table",
            "Move Block C from the table to Block A"
        ]
        
        random_trajectory2 = [
            "Move Block B from Block A to Block C"
        ]
        
        return initial_state, goal_state, solution, [random_trajectory1, random_trajectory2] 