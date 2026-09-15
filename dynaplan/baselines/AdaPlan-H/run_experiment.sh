# Task configuration
export ALFWORLD_DATA='AHP/data/alfworld'
TASK_TYPE="sciworld" # alfworld, sciworld
TEST_MODEL="Meta-Llama-3.1-8B-Instruct" 
METAPLAN_TYPE="none" # none, sft, abp
INCORPORATION_TYPE="query" 
MODEL_PATH="/data/pretrained_models" # the path to the model
SPLIT="test" # test, dev

start_port=8010
start_device=1

api_base="http://localhost:$start_port/v1"
api_key="EMPTY"

# Run the experiment
echo "Start running experiments: $TASK_TYPE $METAPLAN_TYPE $INCORPORATION_TYPE"
echo "Evaluation model: $TEST_MODEL"
if [[ $METAPLAN_TYPE == "none" ]]; then
    echo "xx"
    nohup python -u main.py --exp_config $TASK_TYPE --agent_config agent --model_name ${TEST_MODEL} --split $SPLIT --metaplan_type $METAPLAN_TYPE  --incorporation_type $INCORPORATION_TYPE --api_base $api_base --api_key $api_key > main_dev_qwen_8b.log 2>&1 &
else
    nohup python -u main.py --exp_config $TASK_TYPE --agent_config agent --model_name ${TEST_MODEL} --split $SPLIT --metaplan_type $METAPLAN_TYPE --metaplan_path sciworld_hierarchical_plans_test.json --incorporation_type $INCORPORATION_TYPE --api_base $api_base --api_key $api_key > main_test.log 2>&1 &
fi

