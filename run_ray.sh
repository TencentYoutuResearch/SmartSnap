#!/bin/bash
PROJECT_DIR="$(pwd)"

TRAIN_SCRIPT=${1-"$PROJECT_DIR/scripts/run_qwen3-32b_grpo.sh"}
MASTER_PORT=${2-6379}

ray stop
ray stop
echo "TRAIN_SCRIPT=${TRAIN_SCRIPT}"


export VLLM_USE_V1=1
export MOBILE_SESSION_SAVE_DIR="$PROJECT_DIR/mobile_output"
export DOCKER_MANAGER_TYPE="advanced"
export DOCKER_SCHEDULER_URL="http://$(getent hosts $MASTER_ADDR | awk '{print $1}'):8080"

export BASE_URL="your llm-as-a-judge model url"
export API_KEY="your api key"
export MODEL_NAME="your llm-as-a-judge model name"


pip install hypercorn
pip install weave

WANDB_KEY="xxx"
wandb login ${WANDB_KEY}

echo $PWD
NODE_LIST=${NODE_LIST}
GPUS_PER_NODE=${GPU_NUM_PER_NODE}
NNODES=${NODE_NUM}
NODE_RANK=${INDEX}

if [ "$GPUS_PER_NODE" = "" ]; then
    GPUS_PER_NODE=$(nvidia-smi -L | wc -l)
fi

if [ "$NNODES" = "" ]; then
    NNODES=1
fi

if [ "$NODE_RANK" = "" ]; then
    NODE_RANK=0
fi

echo "GPUS_PER_NODE=${GPUS_PER_NODE}, NNODES=${NNODES}, NODE_RANK=${NODE_RANK}"
POOL_SIZE=$((GPUS_PER_NODE * NNODES))
echo "POOL_SIZE=${POOL_SIZE}"
POOL_SIZE_MAX=$((POOL_SIZE + 10))
echo "POOL_SIZE=${POOL_SIZE}, POOL_SIZE_MAX=${POOL_SIZE_MAX}"


MASTER_ADDR=${MASTER_ADDR}
if [ "${MASTER_ADDR}" = "" ]; then
    export MASTER_ADDR="127.0.0.1"
fi

echo "MASTER_ADDR=${MASTER_ADDR}, MASTER_PORT=${MASTER_PORT}"

# launch the master node of ray in container
echo "Now, running on node index $NODE_RANK"
# 设置内部字段分隔符为逗号
IFS=','

# 将字符串分割成数组
if [ "${NNODES}" = 1 ]; then
    NODE_SUBADDR_IP="127.0.0.1"
    echo "CURRENT IP ADDRESS=${NODE_SUBADDR_IP}"

else
    read -ra NODE_SUBLIST <<< "${NODE_LIST}"
    NODE_SUBADDR=${NODE_SUBLIST[${NODE_RANK}]}
    NODE_SUBADDR_IP="${NODE_SUBADDR%:*}"
    echo "CURRENT IP ADDRESS=${NODE_SUBADDR_IP}"

fi

SUBMIT_MASTER_PORT="8265"
export RAY_ADDRESS="http://127.0.0.1:${SUBMIT_MASTER_PORT}"


if [ "${NODE_RANK}" != "0" ]; then
    # if you want to launch ray on more nodes, use
    echo "Start NODE RANK $NODE_RANK"
    ulimit -u 65536
    ray start --address=${MASTER_ADDR}:${MASTER_PORT} --node-ip-address=${NODE_SUBADDR_IP} --num-gpus=${GPUS_PER_NODE}
    sleep 30
else
    echo "Start MASTER NODE RANK $NODE_RANK"
    ulimit -u 65536
    ray start --head --node-ip-address=${MASTER_ADDR} --port=${MASTER_PORT} --dashboard-host=0.0.0.0 --dashboard-port=${SUBMIT_MASTER_PORT} --num-gpus=${GPUS_PER_NODE}
    sleep 30
fi

if [ "$NNODES" = "1" ]; then
    echo "Start single-node ray submit"
    ulimit -u 65536
    python svagent/advanced_docker_scheduler.py --pool-size ${POOL_SIZE} --max-pool-size ${POOL_SIZE_MAX} --cpu 4000 --memory 16384 &
    sleep 1200
    ray job submit --address="http://127.0.0.1:${SUBMIT_MASTER_PORT}" -- /bin/bash ${TRAIN_SCRIPT} ${MASTER_ADDR} ${MASTER_PORT} ${NODE_RANK}
    sleep 30
else
    echo "Start multi-node ray submit"
    if [ "${NODE_RANK}" = "0" ]; then
        echo "only submit multi-node training from the master"
        ulimit -u 65536
        python svagent/advanced_docker_scheduler.py --pool-size ${POOL_SIZE} --max-pool-size ${POOL_SIZE_MAX} --cpu 4000 --memory 16384 &
        sleep 1200
        ray job submit --address="http://127.0.0.1:${SUBMIT_MASTER_PORT}" -- /bin/bash ${TRAIN_SCRIPT} ${MASTER_ADDR} ${MASTER_PORT} ${NODE_RANK}
    else
        echo "other nodes waiting"
        echo "START GPUS LOADING"
        sleep 365d
    fi
fi
