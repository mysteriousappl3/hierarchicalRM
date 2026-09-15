## 提前为验证集、测试集生成分层规划
## 要求生成的plan的格式保存为
## {
##   "task": "...",
##   "plan": "...",
## }
##先生成了plan之后，再用vllm部署就不用改动相关代码了
import os
import sys
import re
import random
import glob
import json
import yaml
import numpy as np
from gen_plan_utils import create_LLM, load_json_data, save_json_data
from plan_prompt import ALFWORLD_PLAN_GENERATION_TEMPLATE_ADAPTIVE, SCIWORLD_PLAN_GENERATION_TEMPLATE_ADAPTIVE

# Import ALFWorld related modules

llm_planner = create_LLM({
    'model_name': 'Meta-Llama-3.1-8B-Instruct',
    'model_type': 'local',
    'server_port': 8002
})

tmperature = 0.9

def generate_plans_alfworld(task_desc):
    # 生成分层计划
    prompt = ALFWORLD_PLAN_GENERATION_TEMPLATE_ADAPTIVE.format(
        task=task_desc
    )
    plan_response = llm_planner.fast_run(prompt, temperature=tmperature)
    print(plan_response)
        
    plans = {}

    for level in [1, 2, 3]:
        plan_match = re.search(rf'<plan {level}>(.*?)</plan {level}>', plan_response, re.DOTALL)
        if plan_match:
            plans[f"plan_{level}"] = plan_match.group(1).strip()
    
    return plans

def generate_plans_sciworld(task_desc):
    prompt = SCIWORLD_PLAN_GENERATION_TEMPLATE_ADAPTIVE.format(
        task=task_desc
    )
    plan_response = llm_planner.fast_run(prompt, temperature=tmperature)
    print(plan_response)        
    plans = {}
    for level in [1, 2, 3, 4, 5]:
        plan_match = re.search(rf'<plan {level}>(.*?)</plan {level}>', plan_response, re.DOTALL)
        if plan_match:
            plans[f"plan_{level}"] = plan_match.group(1).strip()

    return plans

def get_active_plans(plans):
    active_plans = {}
    # 根据计划级别获取相应的计划
    for level in sorted(range(1, 6)):  # 确保按照级别顺序
        level_key = f"plan_{level}"
        if level_key in plans:
            active_plans[level_key] = plans[level_key]
    
    return active_plans
    # return self.plans

def format_plans_for_prompt(plans):
    active_plans = get_active_plans(plans)
    plans_text = ""
    for level_key, plan_content in active_plans.items():
        level_num = level_key.split("_")[1]
        plans_text += f"--- PLAN LEVEL {level_num} ---\n{plan_content}\n\n"
    ## plan的格式可以进行改变
    return plans_text
    

def gen_plan_alfworld(split="train"):
    # 创建ALFWorld环境
    input_data_path = f'tasks/alfworld_task_{split}.json'
    with open(input_data_path, 'r') as f:
        task_data = json.load(f)
    plans_dict = []
    for i, task_desc in enumerate(task_data):
        print("Task {}:".format(i))
        print(task_desc)
        print("-" * 50)

        plans = generate_plans_alfworld(task_desc)
        plans_text = format_plans_for_prompt(get_active_plans(plans))
        plans_dict.append({
            "task": task_desc,
            "plans_all": plans,
            "plan": plans_text
        })

    save_json_data(plans_dict, f"alfworld_hierarchical_plans_{split}.json")

def gen_plan_sciworld(split="train", pre_path=None):
    input_data_path = f'tasks/sciworld_task_{split}.json'
    with open(input_data_path, 'r') as f:
        task_data = json.load(f)
    print("Total tasks:", len(task_data))
    plans_dict = []
    for i, task in enumerate(task_data):
        task_desc = task['task_desc']
        task_id = task['task_id']
        print("Task {}:".format(i))
        task_desc = task_desc.replace('Task Description:\n', ' ')
        print(task_desc)
        print("-" * 50)

        plans = generate_plans_sciworld(task_desc)
        plans_text = format_plans_for_prompt(get_active_plans(plans))
        plans_dict.append({
            "task_id": task_id,
            "task": task_desc,
            "plans_all": plans,
            "plan": plans_text
        })

    save_json_data(plans_dict, f"{pre_path}/sciworld_hierarchical_plans_{split}.json")


if __name__ == "__main__":
    # 加载配置
    pre_path = '5e5_0.1'
    if not os.path.exists(pre_path):
        os.makedirs(pre_path, exist_ok=True)
    gen_plan_sciworld(split='test', pre_path=pre_path)
    gen_plan_sciworld(split='dev', pre_path=pre_path)
