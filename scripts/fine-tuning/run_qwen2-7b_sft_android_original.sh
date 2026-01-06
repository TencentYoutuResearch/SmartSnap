#!/bin/bash
set -x

master_addr=${1}
master_port=${2}
nnodes=${3}
node_rank=${4}
nproc_per_node=${5}


export WANDB_KEY="xxx"
wandb login ${WANDB_KEY}

echo "master_addr=${master_addr}, master_port=${master_port}, nnodes=${nnodes}, node_rank=${node_rank}, nproc_per_node=${nproc_per_node}"
echo "master_addr=${master_addr}, master_port=${master_port}, nnodes=${nnodes}, node_rank=${node_rank}, nproc_per_node=${nproc_per_node}"
echo "master_addr=${master_addr}, master_port=${master_port}, nnodes=${nnodes}, node_rank=${node_rank}, nproc_per_node=${nproc_per_node}"
echo "master_addr=${master_addr}, master_port=${master_port}, nnodes=${nnodes}, node_rank=${node_rank}, nproc_per_node=${nproc_per_node}"
echo "master_addr=${master_addr}, master_port=${master_port}, nnodes=${nnodes}, node_rank=${node_rank}, nproc_per_node=${nproc_per_node}"

project_name=multiturn-sft
experiment_name=qwen-2.5-7b-androidlab-ft-original

TRAIN_DATA_ANDROID="AndroidLab/training_data_androidlab_open_original.jsonl.paquet"
MODEL_PATH="...models/Qwen2.5-7B-Instruct_Qwen"
SAVE_PATH=...checkpoints_sft/$project_name/$experiment_name
mkdir -p ${SAVE_PATH}

TRAIN_DATA="['$TRAIN_DATA_ANDROID']"
EVAL_DATA="['$TRAIN_DATA_ANDROID']"

torchrun --nnodes=$nnodes \
     --nproc_per_node=$nproc_per_node \
     --master-addr=$master_addr \
     --master-port=$master_port \
     --node-rank=$node_rank \
     -m verl.trainer.fsdp_sft_trainer \
    data.train_files=$TRAIN_DATA \
    data.val_files=$EVAL_DATA \
    data.max_length=32768 \
    data.truncation=right \
    data.train_batch_size=32 \
    data.multiturn.enable=true \
    data.multiturn.messages_key=messages \
    data.multiturn.tools_key=tools \
    data.micro_batch_size_per_gpu=1 \
    model.partial_pretrain=$MODEL_PATH \
    model.strategy=fsdp \
    model.fsdp_config.cpu_offload=True \
    trainer.default_local_dir=$SAVE_PATH \
    trainer.save_freq=100 \
    trainer.project_name=$project_name \
    trainer.experiment_name=$experiment_name \
    trainer.logger='["console","wandb"]' \
    trainer.total_epochs=5 \
    ulysses_sequence_parallel_size=1 \
    use_remove_padding=true

