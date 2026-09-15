## 利用现有的框架如何做评测
# 1. 分割不同层次的plan，但是这里不能保证每个task都有所有的层次。每次从头跑都会涉及到所有的task，没有对应层次plan的task只能够跳过，该怎么进行跳过
import re
import json

def load_json(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)
    return data

def get_plan(plan_pre, level):
    level_list = range(1, level + 1)
    plans = {}
    for level in level_list:
        plan_match = re.search(rf'<plan {level}>(.*?)</plan {level}>', plan_pre, re.DOTALL)
        if plan_match:
            plans[f"plan_{level}"] = plan_match.group(1).strip()
        else:
            return None
            ## 如果达不到最大层次就直接返回None
    
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
    

def split_level_workflow(plans_data, level):
   """
   plan的格式为<plan 1> </plan 1> <plan 2> </plan 2> ...
   根据level进行字符串解析并分割plan
   """
   split_plans = []
   for task_id, plan_dict in plans_data.items():
       plan_dict = get_plan(plan_dict['plan'], level)
       if plan_dict is not None:
           plan_text = format_plans_for_prompt(get_active_plans(plan_dict))
           split_plans.append({
               "id": task_id,
               "workflow": plan_text
           })

   return split_plans

if __name__ == "__main__":
    version = 1
    plan_data = load_json(f"sciworld_train_plan_dict_version_{version}.json")

    for i in range(1, 4):
        split_plans = split_level_workflow(plan_data, i)
        with open(f"sciworld_hierarchical_plans_level_{i}_train_{version}.json", "w") as fw:
            json.dump(split_plans, fw, indent=4)
