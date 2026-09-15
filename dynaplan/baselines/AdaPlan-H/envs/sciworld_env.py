import re
import json
import logging
from typing import Tuple

from scienceworld import ScienceWorldEnv

from envs import BaseEnv
from tasks import SciWorldTask
from prompt import prompt_with_icl
from utils.datatypes import State


logger = logging.getLogger("agent_frame")


class SciWorldEnv(BaseEnv):
    def __init__(
        self,
        task: SciWorldTask,
        env: ScienceWorldEnv,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.task: SciWorldTask = task
        self.env = env
        self.max_steps_dict = json.load(open("data/sciworld/max_steps.json"))

        self.max_error_step = 10
        
        self.state = State()
    
    def parse_action(self, llm_output: str) -> str:
        llm_output = llm_output.strip()
        pattern = re.compile(r"Action:\s?(.*)", re.DOTALL)
        action = re.findall(pattern, llm_output)[0]
        try:
            assert action is not None
            assert 'task complete' not in action.lower()
            return action
        except:
            action = re.findall(pattern, llm_output)[1]
            assert action is not None
            return action
    
    def parse_output(self, llm_output: str) -> str:

        ## 找到第一个Thought的内容和第一个Action的内容
        thought_pattern = re.compile(r"Thought:\s?(.*?)(?=Action:)", re.DOTALL)
        action_pattern = re.compile(r"Action:\s?(.*)", re.DOTALL)
        thought = re.findall(thought_pattern, llm_output)
        action = re.findall(action_pattern, llm_output)
        if thought:
            thought = thought[0].strip()
        else:
            thought = ""
        if action:
            if "contains 'Action: '" in llm_output:
                print(action[1])
                action = action[1].strip().split('\n')[0]
                print("++++++++++++++++++++++++++++++++")
                print(action)
            else:
                action = action[0].strip().split('\n')[0]
        else:
            action = "" 
        if thought:
            formatted_response = f"Thought: {thought}\nAction: {action}"
        else:
            formatted_response = f"Action: {action}"
        print("Formatted Response:", formatted_response)

        return formatted_response
    
    def isrepeat(self) -> bool:
        if len(self.state.history) < 40:
            return False
        contente_list = [item['content'] for item in self.state.history[-20:] if item['role'] == 'assistant']
        if len(set(contente_list)) == 1:  # 最近10次交互都是重复的
            return True
        return False
    
    def step(self, llm_output: str) -> Tuple[str, State]:
        try:
            llm_output = llm_output.replace("'Action: '", "").replace('USER:', '').replace('USER :', '')
            action = self.parse_action(llm_output)
            llm_output = self.parse_output(llm_output)
            self.state.history.append({
                "role": "assistant",
                "content": llm_output
            })
        except:
            self.state.history.append({
                "role": "assistant",
                "content": llm_output
            })
            observation = f"Observation: Invalid format. The input must contains 'Action: '"
            self.state.history.append({
                "role": "user",
                "content": observation,
            })
            self.state.steps += 1
            self.state.reward = 0

            if self.state.steps >= self.max_steps:
                self.state.finished = True
                self.state.success = False
                self.state.terminate_reason = "max_steps"
                self.state.reward = 0
            
            # self.state.error_step += 1
            # if self.state.error_step >= self.max_error_step:
            #     self.state.finished = True
            #     self.state.success = False
            #     self.state.terminate_reason = "max_error_steps"
            return observation, self.state
        try:
            observation, _, done, info = self.env.step(action)
            reward = info['raw_score']

            if "No known action matches that input" in observation:
                self.state.error_step += 1
                if self.state.error_step >= self.max_error_step:
                    self.state.finished = True
                    self.state.success = False
                    self.state.terminate_reason = "max_error_steps"
                # 修改action,符合正确的格式
                observation = observation + " Please modify your action, action should be one of the legal actions."
            else:
                self.state.error_step = 0

            observation = f"Observation: {observation}"
            if self.state.reward is None or reward > self.state.reward:
                self.state.reward = reward
        except AssertionError:
            observation = 'Observation: Invalid action!'
            done = False

        self.state.history.append({
            "role": "user",
            "content": f"{observation}",
        })

        if self.isrepeat():
            self.state.finished = True
            self.state.success = False
            self.state.terminate_reason = "repeated"

        self.state.steps += 1
        if self.state.steps >= self.max_steps:
            self.state.finished = True
            self.state.success = False
            self.state.terminate_reason = "max_steps"

        if done:
            self.state.finished = True
            self.state.success = True
            self.state.terminate_reason = "success"

        return observation, self.state
    
    def reset(self) -> Tuple[str, State]:
        self.state = State()
        self.state.error_step = 0
        self.max_steps = self.max_steps_dict[self.task.sub_task_name]
        self.env.load(self.task.sub_task_name, self.task.variation_idx, simplificationStr="easy", generateGoldPath=False)
        obs, info = self.env.reset()
        cur_task = info['taskDesc']
        self.taskDesc = cur_task
        if self.args.incorporation_type == "query":
            observation, messages = prompt_with_icl(
                instruction=self.instruction,
                raw_icl=self.raw_icl,
                cur_task=cur_task,
                icl_num=1,
                workflow=self.task.workflow,
            )
        else:
            observation, messages = prompt_with_icl(
                instruction=self.instruction,
                raw_icl=self.raw_icl,
                cur_task=cur_task,
                icl_num=1,
                workflow=None,
            )

        if self.icl_format == 'first':
            self.state.history.append({
                "role": "user",
                "content": observation,
            })
        elif self.icl_format == 'conversation':
            self.state.history = messages
        return observation, self.state
