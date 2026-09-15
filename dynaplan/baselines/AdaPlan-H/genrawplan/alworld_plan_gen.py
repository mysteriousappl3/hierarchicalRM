import os
import json
import sys
import re
from tqdm import tqdm

sys.path.append('..')
from ..genplan.gen_plan_utils import chatgpt

action_obs_example = """
"You are in the middle of a room. Looking quickly around you, you see a cabinet 4, a cabinet 3, a cabinet 2, a cabinet 1, a countertop 1, a garbagecan 1, a handtowelholder 2, a handtowelholder 1, a sinkbasin 2, a sinkbasin 1, a toilet 1, a toiletpaperhanger 1, and a towelholder 1.\nYour task is to: put some spraybottle on toilet."
Thought: "To solve the task, I need to find and take a sparybottle, then put it on toilet. First I need to find a spraybottle. A spraybottle is more likely to appear in cabinet (1-4), countertop (1), toilet (1), sinkbasin (1-2), garbagecan (1). I can check one by one, starting with cabinet 1.\nAction: go to cabinet 1"

"Observation: On the cabinet 1, you see a cloth 1, a soapbar 1, a soapbottle 1."
"Action: go to cabinet 2"

"Observation: The cabinet 2 is closed."
"Action: open cabinet 2"

"Observation: You open the cabinet 2. The cabinet 2 is open. In it, you see a candle 1, and a spraybottle 2."
"Thought: Now I find a spraybottle (2). Next, I need to take it.\nAction: take spraybottle 2 from cabinet 2"

"Observation: You pick up the spraybottle 2 from the cabinet 2."
"Thought: Now I take a spraybottle (2). Next, I need to put it in/on toilet 1.\nAction: go to toilet 1"

"Observation: On the toilet 1, you see a soapbottle 2."
"Action: put spraybottle 2 in/on toilet 1"

"Observation: You put the spraybottle 2 in/on the toilet 1."
"""

# 原始示例
PLAN_EXAMPLE = """
#### Example Task:

You are in the middle of a room. Looking quickly around you, you see a cabinet 4, a cabinet 3, a cabinet 2, a cabinet 1, a countertop 1, a garbagecan 1, a handtowelholder 2, a handtowelholder 1, a sinkbasin 2, a sinkbasin 1, a toilet 1, a toiletpaperhanger 1, and a towelholder 1.\nYour task is to: put some spraybottle on toilet."

#### Example Interaction Sequence:

"Observation: You are in the middle of a room. Looking quickly around you, you see a cabinet 4, a cabinet 3, a cabinet 2, a cabinet 1, a countertop 1, a garbagecan 1, a handtowelholder 2, a handtowelholder 1, a sinkbasin 2, a sinkbasin 1, a toilet 1, a toiletpaperhanger 1, and a towelholder 1.\nYour task is to: put some spraybottle on toilet."
"Thought: "To solve the task, I need to find and take a sparybottle, then put it on toilet. First I need to find a spraybottle. A spraybottle is more likely to appear in cabinet (1-4), countertop (1), toilet (1), sinkbasin (1-2), garbagecan (1). I can check one by one, starting with cabinet 1.\nAction: go to cabinet 1"

"Observation: On the cabinet 1, you see a cloth 1, a soapbar 1, a soapbottle 1."
"Action: go to cabinet 2"

"Observation: The cabinet 2 is closed."
"Action: open cabinet 2"

"Observation: You open the cabinet 2. The cabinet 2 is open. In it, you see a candle 1, and a spraybottle 2."
"Thought: Now I find a spraybottle (2). Next, I need to take it.\nAction: take spraybottle 2 from cabinet 2"

"Observation: You pick up the spraybottle 2 from the cabinet 2."
"Thought: Now I take a spraybottle (2). Next, I need to put it in/on toilet 1.\nAction: go to toilet 1"

"Observation: On the toilet 1, you see a soapbottle 2."
"Action: put spraybottle 2 in/on toilet 1"

"Observation: You put the spraybottle 2 in/on the toilet 1."

#### Example Plan:
<plan 1>
Step 1: Find the spraybottle.
Step 2: Take the spraybottle.
Step 3: Put the spraybottle on the toilet.
</plan 1>
<plan 2>
Step 1: Search for a spraybottle in the room (likely locations: cabinet 1-4, countertop, toilet, sinkbasin, garbagecan).
Step 2: Once found, take the spraybottle.
Step 3: Move to the toilet.
Step 4: Place the spraybottle on the toilet.
</plan 2>
<plan 3>
Step 1: Examine potential locations for the spraybottle: Start by checking cabinet 1, then proceed to other cabinets and the countertop.
Step 2: Open the cabinet if needed and search for a spraybottle.
Step 3: If the spraybottle is found, take it.
Step 4: Move towards the toilet.
Step 5: Observe the toilet for any items already on it.
Step 6: Put the spraybottle on the toilet.
</plan 3>
"""

# 用于从交互序列生成计划的模板
PLAN_FROM_TRAJECTORY_TEMPLATE = """I'll show you  a task in a household environment, along with the sequence of observations and actions an agent took to accomplish it. Based on these observations and actions, I'd like you to create a 3-level hierarchical plan with three levels of detail.

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
<plan 3>
Step 1: ...
Step 2: ...
...
</plan 3>

## Notes:
- The key difference between plans is only their level of detail, they should all describe the same overall approach
- Each successive plan should break down the steps of the previous plan into more detailed substeps
- The number of steps should increase with each level: plan 1 has the fewest steps, plan 3 has the most steps
- Plan 1 should provide a high-level overview with general steps
- Plan 2 should expand on plan 1 by breaking down each high-level step into more specific substeps
- Plan 3 should be the most detailed version, breaking down plan 2's steps further, but is still a plan, not executable actions
- When creating plan 3, you can reference the following action formats but do not need to use them directly:
    1. go to {{recep}}
    2. take {{obj}} from {{recep}}
    3. put {{obj}} in/on {{recep}}
    4. open {{recep}}
    5. close {{recep}}
    6. toggle {{obj}} {{recep}}
    7. clean {{obj}} with {{recep}}
    8. heat {{obj}} with {{recep}}
    9. cool {{obj}} with {{recep}}
- Ensure all plans describe the same overall approach, just at different levels of detail
- Make sure each step is clear, concise, and focused on the "what" rather than the exact "how"
- No explanation is needed

## Example of a similar task with plans:
{example_plan}

# Task: 
{task}

# Interaction sequence:
{interaction_sequence}

# Plan:
"""

def load_icl_examples():
    """加载ALFWorld ICL示例数据"""
    example_path = 'experttraj/alfworld_sft.json'
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
        example_plan=PLAN_EXAMPLE
    )
    
    try:
        # print(prompt)
        response = chatgpt(prompt)
        return response
    except Exception as e:
        print(f"Error generating plan from trajectory: {e}")
        return ""

def generate_plans_for_all_examples():
    """为所有ALFWorld ICL示例生成计划并保存"""
    examples = load_icl_examples()
    if not examples:
        return
        
    all_plans = []
    
    # 遍历每种任务类型
    for i, example in enumerate(examples):
        print(f"Generating plans for task {example['id']}...")
        task_plans = []
        
            # 提取任务描述
        task = extract_task_from_example(example['conversations'])
        
        if task:
            # 格式化交互序列
            interaction_sequence = format_interaction_sequence(example['conversations'])
            
            # 从交互序列生成计划
            plan = generate_plan_from_trajectory(task, interaction_sequence)
            
            task_plans.append({
                'task_id': example['id'],
                'game_file': example['game_file'],
                "task": task,
                "plan": plan
            })
        else:
            print("Warning: Could not extract task from example")
        
        all_plans.append(task_plans)

    return all_plans

if __name__ == "__main__":
    # 保存所有计划
    
    m = 2
    for i in range(m):
        all_plans = generate_plans_for_all_examples()

        output_path = 'alfworld_train_plan_dict_version_{}.json'.format(i + 1)
        with open(output_path, 'w') as f:
            json.dump(all_plans, f, indent=2)
        
        print(f"All plans generated and saved to {output_path}")