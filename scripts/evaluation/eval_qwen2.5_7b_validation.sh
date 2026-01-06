# run on 8xH20
# make sure your current working directory is the root of the project
MASTER_ADDR=${1-"127.0.0.1"}
set -x

ulimit -n 65535
export HYDRA_FULL_ERROR=1
# export CUDA_LAUNCH_BLOCKING=0
export NCCL_DEBUG=INFO

# export NCCL_IB_DISABLE=1  # disables InfiniBand, which can help if you’re on Ethernet.
# export NCCL_P2P_DISABLE=0
# export NCCL_SOCKET_IFNAME=eth0  # or your network interface
# export NCCL_ASYNC_ERROR_HANDLING=1  # helps NCCL recover from errors and report them more clearly.
# export NCCL_IB_GID_INDEX=3
# export NCCL_DEBUG_SUBSYS=ALL
# export NCCL_BLOCKING_WAIT=1

export NCCL_TIMEOUT=7200
export NCCL_SOCKET_TIMEOUT=7200

# export GLOO_SOCKET_IFNAME=eth0
# export NCCL_IB_CUDA_SUPPORT=1
# export NCCL_ALGO=Tree
date=${1}

WANDB_KEY="xxx"
wandb login ${WANDB_KEY}

PROJECT_DIR="$(pwd)"

if [ -z "$date" ]; then
    date=$(date '+%Y%m%d_%H%M%S')
fi

echo "date=${date}"
### 使用非思考模式
MODEL_PATH="...models/Qwen2.5-7B-Instruct_Qwen"

TRAIN_FILE_PATH="data_train_qwen_inst/all_apps_combined.parquet"
TEST_FILE_PATH="data_test_qwen_inst/all_apps_combined.parquet"

PROJECT_NAME='svagent'
EXPERIMENT_NAME="qwen2.5-7b_baseline"
echo "EXPERIMENT_NAME=${EXPERIMENT_NAME}"

default_local_dir=checkpoints/$PROJECT_NAME/$EXPERIMENT_NAME
mkdir -p ${default_local_dir}

python -m verl.trainer.main_ppo \
    algorithm.adv_estimator=grpo \
    data.train_files=$TRAIN_FILE_PATH \
    data.val_files=$TEST_FILE_PATH \
    data.train_batch_size=4 \
    data.val_batch_size=32 \
    data.max_prompt_length=4500 \
    data.max_response_length=27500 \
    data.truncation='error' \
    data.return_raw_chat=True \
    actor_rollout_ref.model.path=$MODEL_PATH \
    actor_rollout_ref.actor.optim.lr=1e-5 \
    actor_rollout_ref.model.use_remove_padding=True \
    actor_rollout_ref.actor.ppo_mini_batch_size=4 \
    actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1 \
    actor_rollout_ref.actor.use_kl_loss=False \
    actor_rollout_ref.actor.kl_loss_coef=0.001 \
    actor_rollout_ref.actor.kl_loss_type=low_var_kl \
    actor_rollout_ref.actor.entropy_coeff=0.001 \
    actor_rollout_ref.model.enable_gradient_checkpointing=True \
    actor_rollout_ref.actor.fsdp_config.param_offload=False \
    actor_rollout_ref.actor.fsdp_config.optimizer_offload=False \
    actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1 \
    actor_rollout_ref.rollout.tensor_model_parallel_size=4 \
    actor_rollout_ref.rollout.name=vllm \
    actor_rollout_ref.rollout.mode=async \
    actor_rollout_ref.rollout.multi_turn.max_parallel_calls=1 \
    actor_rollout_ref.rollout.multi_turn.max_user_turns=20 \
    actor_rollout_ref.rollout.multi_turn.max_assistant_turns=20 \
    actor_rollout_ref.rollout.gpu_memory_utilization=0.7 \
    actor_rollout_ref.rollout.n=16 \
    actor_rollout_ref.rollout.val_kwargs.n=1 \
    actor_rollout_ref.rollout.temperature=1 \
    actor_rollout_ref.rollout.max_model_len=32000 \
    actor_rollout_ref.rollout.max_num_batched_tokens=32000 \
    actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1 \
    actor_rollout_ref.ref.fsdp_config.param_offload=True \
    actor_rollout_ref.rollout.multi_turn.max_tool_response_length=12000 \
    actor_rollout_ref.rollout.multi_turn.tool_config_path="$PROJECT_DIR/mobile_tool_config.json" \
    algorithm.use_kl_in_reward=False \
    trainer.critic_warmup=0 \
    trainer.logger=['console','wandb'] \
    trainer.project_name=${PROJECT_NAME} \
    trainer.experiment_name=${EXPERIMENT_NAME} \
    trainer.n_gpus_per_node=8 \
    trainer.nnodes=4 \
    trainer.save_freq=5 \
    trainer.test_freq=5 \
    trainer.total_epochs=60 \
    trainer.val_only=True \
    trainer.val_before_train=True \
    custom_reward_function.path="$PROJECT_DIR/svagent/mobile_reward_fn.py" \
    custom_reward_function.name=compute_score \
    reward_model.reward_manager=dapo \
    +reward_model.reward_kwargs.overlong_buffer_cfg.enable=False \
    +reward_model.reward_kwargs.overlong_buffer_cfg.len=3072 \
    +reward_model.reward_kwargs.max_resp_len=4096 \
    actor_rollout_ref.actor.clip_ratio_low=0.2 \
    actor_rollout_ref.actor.clip_ratio_high=0.28 \
    actor_rollout_ref.actor.clip_ratio_c=10.0 \
    actor_rollout_ref.actor.loss_agg_mode="seq-mean-token-sum-norm" \
    algorithm.norm_adv_by_std_in_grpo=False \
    trainer.resume_mode=auto \
    trainer.default_local_dir=$default_local_dir \
    trainer.rollout_data_dir=$default_local_dir/rollout \
    trainer.validation_data_dir=$default_local_dir/validation
