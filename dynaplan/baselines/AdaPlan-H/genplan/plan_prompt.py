ALFWORLD_PLAN_GENERATION_TEMPLATE_ADAPTIVE = """Please generate hierarchical plans for a household task based on its difficulty level:
<task>
{task}
</task>

The number of plans and their levels of detail should adjust according to the difficulty of the task:
- Easy tasks should have 1 level plan (high-level overview).
- Medium tasks should have 2 level plans (overview and a bit more detail).
- Difficult tasks should have 3 level plans (overview, intermediate detail, and highly detailed breakdown).

The generated plans should be written in the following format:
<plan 1>
Step 1: ...
Step 2: ...
...
</plan 1>
...
<plan N>
Step 1: ...    
Step 2: ...
...
</plan N>
Where N is the number of plan levels based on task difficulty.

# Your plan for this task:
"""

SCIWORLD_PLAN_GENERATION_TEMPLATE_ADAPTIVE = """Please generate hierarchical plans for a scientific task in a scientific environment based on its difficulty level.
The task difficulty can be inferred from the environment description and the task itself.

<task>
You are a helpful assistant to do some scientific experiment in an environment.
In the environment, there are several rooms: kitchen, foundry, workshop, bathroom, outside, living room, bedroom, greenhouse, art studio, hallway.
{task}
</task>

The generated plans should be written in the following format:
<plan 1>
Step 1: ...
Step 2: ...
...
</plan 1>
...
<plan N>
Step 1: ...    
Step 2: ...
...
</plan N>
Where N is the number of plan levels based on task difficulty.

## Notes:
The number of plans and their levels of detail should adjust according to the difficulty of the task:
- Easy tasks should have 1 level plan (high-level overview).
- Medium tasks should have 2 level plans (overview and a bit more detail).
- Difficult tasks should have 3 level plans (overview, intermediate detail, and highly detailed breakdown).
- When creating the plan level 3, you can reference the following action formats to describe specific actions:
    1. open OBJ: open a container
    2. close OBJ: close a container
    3. activate OBJ: activate a device
    4. deactivate OBJ: deactivate a device
    5. connect OBJ to OBJ: connect electrical components
    6. disconnect OBJ: disconnect electrical components
    7. use OBJ [on OBJ]: use a device/item
    8. look around: describe the current room
    9. examine OBJ: describe an object in detail
    10. look at OBJ: describe a container's contents
    11. read OBJ: read a note or book
    12. move OBJ to OBJ: move an object to a container
    13. pick up OBJ: move an object to the inventory
    14. pour OBJ into OBJ: pour a liquid into a container
    15. mix OBJ: chemically mix a container
    16. teleport to LOC: teleport to a specific room
    17. focus on OBJ: signal intent on a task object
    18. wait: task no action for 10 steps
    19. wait1: task no action for a step

# Your plan for this task:
"""
