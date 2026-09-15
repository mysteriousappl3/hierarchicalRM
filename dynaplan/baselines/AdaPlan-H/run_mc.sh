# Task configuration
export ALFWORLD_DATA='AHP/data/alfworld'
TASK_TYPE="sciworld" # alfworld, sciworld
TEST_MODEL="Meta-Llama-3.1-8B-Instruct" 
METAPLAN_TYPE="mc" # none, sft, rft, mpo
INCORPORATION_TYPE="query" # query, observation, thought
MODEL_PATH="/data/pretrained_models" # the path to the model
SPLIT="train" # test, dev

start_port_1=8082
api_base_1="http://localhost:$start_port_1/v1"
api_key="EMPTY"

start_port_2=8084
api_base_2="http://localhost:$start_port_2/v1"

start_port_3=8086
api_base_3="http://localhost:$start_port_3/v1"

# Run the experiment
echo "Start running experiments: $TASK_TYPE $METAPLAN_TYPE $INCORPORATION_TYPE"
echo "Evaluation model: $TEST_MODEL"
# Run mc method, file_id indicates plan version, run_id indicates different runs for the same plan version
file_id=1
run_id=1

nohup python -u main.py \
    --exp_config $TASK_TYPE \
    --agent_config agent \
    --model_name ${TEST_MODEL} \
    --split $SPLIT \
    --metaplan_type $METAPLAN_TYPE \
    --metaplan_path genrawplan/${TASK_TYPE}_hierarchical_plans_level_1_train_$file_id.json \
    --incorporation_type $INCORPORATION_TYPE \
    --output_dir mc/${TASK_TYPE}/plan_${file_id}_level_1_run_${run_id} \
    --api_base $api_base_1 \
    --api_key $api_key > test_1.log 2>&1 &

nohup python -u main.py \
    --exp_config $TASK_TYPE \
    --agent_config agent \
    --model_name ${TEST_MODEL} \
    --split $SPLIT \
    --metaplan_type $METAPLAN_TYPE \
    --metaplan_path genrawplan/${TASK_TYPE}_hierarchical_plans_level_2_train_$file_id.json \
    --incorporation_type $INCORPORATION_TYPE \
    --output_dir mc/${TASK_TYPE}/plan_${file_id}_level_2_run_${run_id} \
    --api_base $api_base_2 \
    --api_key $api_key > test_2.log 2>&1 &

nohup python -u main.py \
    --exp_config $TASK_TYPE \
    --agent_config agent \
    --model_name ${TEST_MODEL} \
    --split $SPLIT \
    --metaplan_type $METAPLAN_TYPE \
    --metaplan_path genrawplan/${TASK_TYPE}_hierarchical_plans_level_3_train_$file_id.json \
    --incorporation_type $INCORPORATION_TYPE \
    --output_dir mc/${TASK_TYPE}/plan_${file_id}_level_3_run_${run_id} \
    --api_base $api_base_3 \
    --api_key $api_key > test_3.log 2>&1 &


