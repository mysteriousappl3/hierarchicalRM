import json
import re
import os
import sys
sys.path.append('..')
from ..genplan.gen_plan_utils import chatgpt

api_key = "xx"
base_url = "xx"

action_obs_example = """
"Observation: Your task is to use chemistry to create green paint. When you are done, focus on the green paint."
"Thought: I need to find materials to create green paint, which are likely to be found in an art studio.\nAction: look around"

"Observation: This room is called the bedroom. In it, you see: \n\tthe agent\n\ta substance called air\n\ta bed. On the bed is: a mattress. On the mattress is: a white pillow..\n\ta closet. The closet door is open. In the closet is: nothing.\n\ta picture\n\ta table. On the table is: nothing.\nYou also see:\n\tA door to the hallway (that is open)"
"Thought: The bedroom doesn't have the materials I need. I should go to a place where paint and painting supplies are likely to be found, such as an art studio.\nAction: teleport to art studio"

"Observation: You teleport to the art studio."
"Thought: Now that I'm in the art studio, I should look around to find the necessary materials to create green paint.\nAction: look around"

"Observation: This room is called the art studio. In it, you see: \n\tthe agent\n\ta substance called air\n\ta large cupboard. The large cupboard door is open. In the large cupboard is: a drawer, a wood cup (containing yellow paint), a wood cup (containing blue paint), a wood cup (containing red paint).\n\ta table. On the table is: a glass cup (containing nothing).\n\ta wood cup (containing yellow paint)\n\ta wood cup (containing blue paint)\n\ta wood cup (containing red paint)\nYou also see:\n\tA door to the hallway (that is open)"
"Thought: I see blue paint here, which is one of the primary colors needed to mix green paint. I should start by pouring it into an empty container to mix with another color.\nAction: pour cup containing blue paint in art studio in cup containing nothing"

"Observation: You pour the contents of the wood cup into the glass cup."
"Thought: Yellow paint is the other primary color needed to mix with blue to create green. I should add the yellow paint to the container with blue paint.\nAction: pour cup containing yellow paint in art studio in cup containing blue paint in table"

"Observation: You pour the contents of the wood cup into the glass cup."
"Thought: Now that I have both blue and yellow paint in the same container, I need to mix them together to create green paint.\nAction: mix cup containing blue paint and yellow paint"

"Observation: Blue and yellow paint mix to produce green paint."
"Thought: The task is to create green paint and then focus on it. Now that the green paint is made, I should concentrate on the final product.\nAction: focus on green paint"
"""

PLAN_EXAMPLE = """
#### Example Task:  
You are a helpful assistant to do some scientific experiment in an environment.
In the environment, there are several rooms: kitchen, foundry, workshop, bathroom, outside, living room, bedroom, greenhouse, art studio, hallway.
Your task is to use chemistry to create green paint. When you are done, focus on the green paint.

#### Example Interaction Sequence:

"Observation: Your task is to use chemistry to create green paint. When you are done, focus on the green paint."
"Thought: I need to find materials to create green paint, which are likely to be found in an art studio.\nAction: look around"

"Observation: This room is called the bedroom. In it, you see: \n\tthe agent\n\ta substance called air\n\ta bed. On the bed is: a mattress. On the mattress is: a white pillow..\n\ta closet. The closet door is open. In the closet is: nothing.\n\ta picture\n\ta table. On the table is: nothing.\nYou also see:\n\tA door to the hallway (that is open)"
"Thought: The bedroom doesn't have the materials I need. I should go to a place where paint and painting supplies are likely to be found, such as an art studio.\nAction: teleport to art studio"

"Observation: You teleport to the art studio."
"Thought: Now that I'm in the art studio, I should look around to find the necessary materials to create green paint.\nAction: look around"

"Observation: This room is called the art studio. In it, you see: \n\tthe agent\n\ta substance called air\n\ta large cupboard. The large cupboard door is open. In the large cupboard is: a drawer, a wood cup (containing yellow paint), a wood cup (containing blue paint), a wood cup (containing red paint).\n\ta table. On the table is: a glass cup (containing nothing).\n\ta wood cup (containing yellow paint)\n\ta wood cup (containing blue paint)\n\ta wood cup (containing red paint)\nYou also see:\n\tA door to the hallway (that is open)"
"Thought: I see blue paint here, which is one of the primary colors needed to mix green paint. I should start by pouring it into an empty container to mix with another color.\nAction: pour cup containing blue paint in art studio in cup containing nothing"

"Observation: You pour the contents of the wood cup into the glass cup."
"Thought: Yellow paint is the other primary color needed to mix with blue to create green. I should add the yellow paint to the container with blue paint.\nAction: pour cup containing yellow paint in art studio in cup containing blue paint in table"

"Observation: You pour the contents of the wood cup into the glass cup."
"Thought: Now that I have both blue and yellow paint in the same container, I need to mix them together to create green paint.\nAction: mix cup containing blue paint and yellow paint"

"Observation: Blue and yellow paint mix to produce green paint."
"Thought: The task is to create green paint and then focus on it. Now that the green paint is made, I should concentrate on the final product.\nAction: focus on green paint"

#### Example Plan:
<plan 1>
Step 1: Teleport to the art studio.
Step 2: Look around to find blue and yellow paint.
Step 3: Mix the blue and yellow paints to create green paint.
Step 4: Focus on the green paint.
</plan 1>
<plan 2>
Step 1: Teleport to the art studio.
Step 2: Look around and find the cupboard with paint supplies.
Step 3: Identify the blue and yellow paints.
Step 4: Pour blue paint into an empty container.
Step 5: Pour yellow paint into the same container.
Step 6: Mix the paints to create green paint.
Step 7: Focus on the green paint.
</plan 2>
<plan 3>
Step 1: Teleport to the art studio.
    - Action: teleport to art studio
Step 2: Look around the art studio and locate the cupboard containing yellow, blue, and red paints.
    - Action: look around
Step 3: Identify the blue and yellow paints as the necessary ingredients to make green paint.
    - Action: examine blue paint
    - Action: examine yellow paint
Step 4: Pour the contents of the blue paint cup into an empty glass cup.
    - Action: pour blue paint into cup containing nothing
Step 5: Pour the contents of the yellow paint cup into the same glass cup that contains blue paint.
    - Action: pour yellow paint into cup containing blue paint
Step 6: Mix the blue and yellow paints together in the glass cup to create green paint.
    - Action: mix blue and yellow paint
Step 7: Focus on the green paint to complete the task.
    - Action: focus on green paint
</plan 3>
"""

PLAN_FROM_TRAJECTORY_TEMPLATE = """I'll show you a task in a scientific environment, along with the sequence of observations and actions an agent took to accomplish it. Based on these observations and actions, I'd like you to create a 3-level hierarchical plan with 3 levels of detail.

The generated plans should be written in the following format:
<plan 1>
Step 1: ...
Step 2: ...
...
</plan 1>
<plan 2>
Step 1: ...
Step 2: ...
...
</plan 2>
...
<plan 3>
...
</plan 3>

##Notes:
- The key difference between plans is only their level of detail - they should all describe the same overall approach
- Each successive plan should break down the steps of the previous plan into more detailed substeps
- The number of steps should increase with each level: plan 1 has the fewest steps, plan 3 has the most steps
- Plan 1 should provide a high-level overview with general steps
- Plan 2 should expand on plan 1 by breaking down each high-level step into more specific substeps
- Plan 3 should expand on plan 3 by breaking down each step into even more specific substeps and actions
- When creating plan 3, you can reference the following action formats to describe specific actions:
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
- Ensure all plans describe the same overall approach, just at different levels of detail
- Make sure each step is clear, concise, and focused on the "what" rather than the exact "how"
- No explanation is needed

## Action must be in the above format, otherwise it will be invalid. 
## The condition of action is placed before 'Action: ', for example:
step 1: If the blue light bulb is on (metal pot conducts electricity), move the metal pot to the blue box.
    - Action: move metal pot to blue box
## The OBJ in the action must not be specific objects not in Task, for example:
- Wrong: Action: pick up the red apple
- Right: Action: pick up apple

## Plan Example:
{PLAN_EXAMPLE}

## Task: 
You are a helpful assistant to do some scientific experiment in an environment.
In the environment, there are several rooms: kitchen, foundry, workshop, bathroom, outside, living room, bedroom, greenhouse, art studio, hallway.
{task}

## Interaction sequence:
{interaction_sequence}
## Plan:
"""

def save_json(data, file_path):
    """将数据保存为JSON文件"""
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)

def load_json(file_path):
    """从JSON文件加载数据"""
    with open(file_path, 'r') as f:
        return json.load(f)

def load_icl_examples():
    """加载ALFWorld ICL示例数据"""
    example_path = 'experttraj/sciworld_sft.json'
    if os.path.exists(example_path):
        with open(example_path, 'r') as f:
            return json.load(f)
    else:
        print(f"Error: Example file {example_path} not found")
        return {}

def extract_task_from_example(example):
    # 从第一个用户消息中提取任务
    for i, item in enumerate(example):
        if i == 0 or i == 1:
            continue
        if item["from"] == "human":
            content = item["value"]
            return content

    return ""

def format_interaction_sequence(example):
    """将示例交互序列格式化为可读形式"""
    if not example:
        return ""
    
    sequence = ""
    for i, item in enumerate(example):
        if i == 0 or i== 1:
            # 跳过第一个用户消息和第二个助手消息
            continue
        if item["from"] == "human":
            sequence += f"Observation: {item['value']}\n\n"
        elif item["from"] == "gpt":
            sequence += f"{item['value']}\n\n"
    
    return sequence

def generate_plan_from_trajectory(task, interaction_sequence):
    """根据任务和交互序列生成分层计划"""
    prompt = PLAN_FROM_TRAJECTORY_TEMPLATE.format(
        task=task,
        interaction_sequence=interaction_sequence,
        PLAN_EXAMPLE=PLAN_EXAMPLE
    )
    
    # print(prompt)
    response = chatgpt(prompt)
    # print(response)
    return response
    

def get_level_num(conversation):
    item_num = len(conversation)
    # print("item num:", item_num)
    if item_num <= 20:
        return 3
    elif item_num <= 40:
        return 4
    else:
        return 5

def generate_plans_for_all_examples(m):
    """为所有ALFWorld ICL示例生成计划并保存"""
    output_path = f'sciworld_train_plan_dict_version_{m+1}.json'

    if os.path.exists(output_path):
        all_plans = load_json(output_path)
    else:
        all_plans = {}
    
    examples = load_icl_examples()
    if not examples:
        return
    
    # 遍历每种任务类型
    for i, example in enumerate(examples):
        print(f"Generating plans for task {example['id']}...")

        task_id = example['id']
        
            # 提取任务描述
        task = extract_task_from_example(example['conversations'])

        # level = get_level_num(example['conversations'])
        # nums_dict[str(level)] += 1
        if task_id in all_plans:
            if all_plans[task_id]['plan'] is None:
                interaction_sequence = format_interaction_sequence(example['conversations'])
                # 从交互序列生成计划
                plan = generate_plan_from_trajectory(task, interaction_sequence)
                    
                all_plans[task_id] = {
                    'task': task,
                    'plan': plan
                }
        elif task_id not in all_plans and task:
            # 格式化交互序列
            interaction_sequence = format_interaction_sequence(example['conversations'])
            
            # 从交互序列生成计划
            plan = generate_plan_from_trajectory(task, interaction_sequence)

            all_plans[task_id] = {
                'task': task,
                'plan': plan
            }
        else:
            print("Warning: Could not extract task from example")

        # if task_id in all_plans:
        #     if all_plans[task_id]['plan'] is None:
        #         interaction_sequence = format_interaction_sequence(example['conversations'])
        #         # 从交互序列生成计划
        #         plan = generate_plan_from_trajectory(task, interaction_sequence)

        #         # while plan is None and level != 0:
        #         #     level = level - 1
        #         #     plan = generate_plan_from_trajectory(task, interaction_sequence, level)
                    
        #         all_plans[task_id] = {
        #             'task': task,
        #             'plan': plan
        #         }
        # elif task_id not in all_plans and task:
        #     # 格式化交互序列
        #     interaction_sequence = format_interaction_sequence(example['conversations'])
            
        #     # 从交互序列生成计划
        #     plan = generate_plan_from_trajectory(task, interaction_sequence, level)

        #     # while plan is None and level != 0:
        #     #         level = level - 1
        #     #         plan = generate_plan_from_trajectory(task, interaction_sequence, level)
            
        #     all_plans[task_id] = {
        #         'task': task,
        #         'plan': plan
        #     }
        # else:
        #     print("Warning: Could not extract task from example")
        
        save_json(all_plans, f'sciworld_train_plan_dict_version_{m+1}.json')

        print(f"{i+1} tasks processed.")

    return all_plans

if __name__ == "__main__":
    # 保存所有计划

    # output_path = '../ScienceworldPlanGen/sciworld_train_plan_version_1483.json'

    # if os.path.exists(output_path):
    #     all_plans = load_json(output_path)
    
    # ## 需要改变一下之前保存的plan的格式
    # tasks_set = set()
    # plans_dict = {}
    # if all_plans:
    #     for i, task_plans in enumerate(all_plans):
    #         tasks_set.add(task_plans[0]['task_id'])
    #         plans_dict[task_plans[0]['task_id']] = {
    #             'task': task_plans[0]['task'],
    #             'plan': task_plans[0]['plan']
    #         }
    # save_json(plans_dict, 'sciworld_train_plan_dict_version_1.json')

    all_plans = generate_plans_for_all_examples(2)



