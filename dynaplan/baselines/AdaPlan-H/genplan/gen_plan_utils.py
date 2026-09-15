import openai
from openai import OpenAI
import concurrent
from time import sleep
import json
import sys
sys.path.append('..')

api_key = "sk-uQ3Q4igYxnqjrEAcXfatMws18iO180Vn8dFRSYPcpmj3Zpc2"
base_url = "https://api.chatanywhere.tech/v1"


def chatgpt(prompt, response_format=None):
    client = openai.OpenAI(
                    base_url=base_url,
                    api_key=api_key)

    # 调用API生成文本
    try:
        response = client.chat.completions.create(
            model='gpt-4o-ca',
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            response_format=response_format
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        print(f"Error: {e}")
        return None
    
def chatgpt_model(prompt, model_name, response_format=None):
    client = openai.OpenAI(
                    base_url=base_url,
                    api_key=api_key)

    # 调用API生成文本
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            response_format=response_format
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        print(f"Error: {e}")
        return None


def load_json_data(path):
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    return data

def save_json_data(data, path):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def create_LLM(llm_config):
    if llm_config['model_name'] == 'Qwen2.5-7B':
        return Local_LLM(llm_config)
    if llm_config['model_name'] == 'Meta-Llama-3.1-8B-Instruct':
        return Local_LLM(llm_config)
    if llm_config['model_name'] == 'gpt-4o-mini':
        return GPT_LLM(llm_config)
    if llm_config['model_name'] == 'gpt-4o-ca':
        return GPT_LLM(llm_config)
    
class LLM():
    def __init__(self, config):
        self.config = config
        self.model_name = config['model_name']
        self.model_type = config['model_type']    # Include 'remote' and 'local'.

    def fast_run(self, query, response_format):
        raise NotImplementedError
    

class GPT_LLM(LLM):
    def __init__(self, config):
        super().__init__(config)
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = config['model_name']

    def fast_run(self, query, response_format=None, temperature=1.0, penalty_score=0.0):
        return chatgpt_model(query, self.model_name, response_format)
    

class Local_LLM(LLM):
    def __init__(self, config):
        super().__init__(config)
    
        self.server_port = config['server_port']
        self.client = OpenAI(api_key='none', base_url="http://localhost:%d/v1" % self.server_port)

    def run(self, message_list, response_format, temperature=1.0):
        if response_format:
            response = self.client.chat.completions.create(
                model=self.config['model_name'],
                messages=message_list,
                temperature=temperature,
                response_format=response_format
            )
        else:
            response = self.client.chat.completions.create(
                model=self.config['model_name'],
                messages=message_list,
                temperature=temperature
            )
 
        response = self.parse_response(response)
        return response
    
    def parse_response(self, response):
        return {
            # 'result': response.res_message
            'result': response.choices[0].message.content,
        }

    def fast_run(self, query, response_format=None, temperature=1.0):
        # print(query)
        try:
            response = self.run([{"role": "user", "content": query}], response_format, temperature)
        except openai.BadRequestError:
            response = self.run([{"role": "user", "content": query[:4096]}], response_format, temperature)
        # print(response)
        return response['result']

