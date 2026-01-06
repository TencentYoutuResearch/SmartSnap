<div align="center">
  <img src="https://raw.githubusercontent.com/yuleiqin/images/master/SmartSnap/mascot_smartsnap.png" width="400"/>
</div>

<p align="center">
  <a href="https://arxiv.org/abs/2512.22322">
    <img src="https://img.shields.io/badge/arXiv-Paper-red?style=flat-square&logo=arxiv" alt="arXiv Paper"></a>
  &nbsp;
</p>


We introduce **SmartSnap**, a paradigm shift that transforms GUI agents📱💻🤖 from passive task executors into proactive self-verifiers. By empowering agents to curate their own evidence of success through the **3C Principles** (Completeness, Conciseness, Creativity), we eliminate the bottleneck of expensive post-hoc verification while boosting reliability and performance on complex mobile tasks.

# 📖 Overview

SmartSnap redefines the agent's role through a unified policy that handles both **task execution** and **evidence curation**. Instead of burdening verifiers with verbose, noisy interaction trajectories, agents learn to select minimal, decisive snapshot evidences from their tool interactions. The framework leverages:

- **Augmented MDP**: Agents operate in an extended action space ⊕ consisting of execution actions (click, type, etc.) and curation actions (submit evidence indices)
- **Dual-objective training**: GRPO-based RL optimizes for both task completion and evidence quality
- **Dense reward shaping**: Multi-component rewards $R_{format}$ + $R_{validity}$ + $R_{complete}$ + $R_{concise}$ guide agents toward becoming effective self-verifiers
- **Creative evidence generation**: Agents proactively execute additional actions post-task to capture robust proof when needed

The approach achieves up to **26.08% absolute performance gains** on AndroidLab across model scales, matching or exceeding much larger models like DeepSeek-V3.1 and Qwen3-235B-A22B.


![The core concept of our proposed SPEAR.](https://raw.githubusercontent.com/yuleiqin/images/master/SmartSnap/comparison.png)


# 📦 Releasing Contents

We release the following resources to accelerate research in self-verifying agents:

1. **Model Checkpoints** (HuggingFace Hub):
   - `SmartSnap-Llama3.1-8B-Instruct` - RL-trained with 31.15% SR
   - `SmartSnap-Qwen2.5-7B-Instruct` - RL-trained with 30.43% SR  
   - `SmartSnap-Qwen3-8B-Instruct` - RL-trained with 36.23% SR
   - `SmartSnap-Qwen3-32B-Instruct` - RL-trained with 34.78% SR
   - Corresponding SFT checkpoints for each model family

2. **Training Dataset**:
   - 550K+ QA pairs from 30K+ curated trajectories on AndroidLab
   - Evidence annotations following the 3C Principles
   - XML-based environment observations and tool interaction logs

3. **Evaluation Suite**:
   - AndroidLab benchmark integration (138 validation tasks across 9 apps)
   - LLM-as-a-Judge evaluation pipeline (GLM4-based)
   - Verifier implementation using DeepSeek-R1 with majority voting

4. **System Prompts**:
   - Agent system prompt (~4K tokens) encoding the 3C Principles
   - Verifier instructions for structured evidence assessment
   - Reward shaping configuration files



# ⌨️ Quick Start

- Download the necessary docker image from [AndroidLab](https://github.com/THUDM/Android-Lab).

- Prepare your own docker environments for online rollout interaction. We provide an example with the Tencent Cloud Sandbox usage. You can refer to `svagent/docker_client_tione.py` for more details. Make sure the `.env` contains the necessary Tencent Cloud credentials.

- Install [VeRL@v0.5.0](https://github.com/volcengine/verl/releases/tag/v0.5.0) for distributed RL training. We also provide a modified version which supports more hyper-parameters for RL training tricks proposed in [SPEAR](https://github.com/TencentYoutuResearch/SPEAR).

```
git clone https://github.com/TencentYoutuResearch/SPEAR.git
cd SPEAR/verl
pip install --no-deps -e .
```

Make sure all the required packages are installed properly.


- Install SmartSnap for training Self-Verifying Agent (SVAgent).

```
cd SmartSnap
pip install --no-deps -e .
```

- Download the necessary training and evaluation data from HuggingFace🤗 for [SFT](https://huggingface.co/datasets/yolay/SmartSnap-FT) and [RL](https://huggingface.co/datasets/yolay/SmartSnap-RL).

## Fine-Tuning with VeRL

- Check the training scripts in `scripts/fine-tuning`.


## Reinforcement Learning with VeRL

- Check the training scripts in `scripts/llama`, `scripts/qwen2.5`, `scripts/qwen3`, and `scripts/qwen3-32b`. Check the evaluation scripts in `scripts/evaluation`. Make sure all the necessary paths (e.g., model, dataset), wandb API KEY, and LLM-as-a-Judge model URL and name (`run_ray.sh`) are correctly specified.

## Submit Training Jobs

- We follow VeRL to use ray for distributed training. Submit your training script via `run_ray.sh` with the necessary hyper-parameters (e.g., `TRAIN_SCRIPT` and `MASTER_PORT`).

# 💡 Key take-home Messages

- **Synergistic learning loop**: The dual mission of executing and verifying cultivates deeper task understanding—agents learn to decompose problems into evidence milestones, implicitly improving planning capabilities.

- **Evidence quality matters**: Vanilla SFT only achieves ~22% SR across models, while self-verifying SFT reaches 23-30% SR, demonstrating that evidence curation training is more effective than solution memorization.

- **RL unlocks generalization**: Fine-tuned models show consistent >16% absolute gains after RL training, with smaller models (8B) outperforming their naive prompting baselines by **26.08%**.

- **Efficiency through conciseness**: Trained agents converge to submitting **~1.5 evidence snapshots** on average, drastically reducing verifier costs while maintaining high reliability.

- **Limitations**: Tasks requiring extensive domain knowledge (e.g., Maps.me navigation) remain challenging without explicit knowledge injection, suggesting RL alone cannot bridge large knowledge gaps.

# 📊 Experimental Results

| Type | Model | SR | Sub-SR | RRR | ROR |
|------|-------|----|--------|-----|-----|
| **PT** | GPT-4o | 25.36 | 30.56 | **107.45** | 86.56 |
| **PT** | GPT-4-1106-Preview | 31.16 | 38.21 | 66.34 | 86.24 |
| **PT** | Gemini-1.5-Pro | 18.84 | 22.40 | 57.72 | 83.99 |
| **PT** | Gemini-1.00 | 8.70 | 10.75 | 51.80 | 71.08 |
| **PT** | GLM4-Plus | 27.54 | 32.08 | 92.35 | 83.41 |
| **PT** | DeepSeek-V3.1 | **36.23** | <u>40.95</u> | 81.01 | 94.63 |
| **PT** | Qwen3-235B-A22B | <u>34.78</u> | 38.76 | 83.35 | 89.48 |
|  | **Act-only**<sup>*</sup> |  |  |  |  |
| **PT** | LLaMA3.1-8B-Instruct<sup>‡</sup> | 2.17 | 3.62 | — | 52.77 |
| **FT**<sup>†</sup> | LLaMA3.1-8B-Instruct<sup>‡</sup> | 23.91<sup>(+21.74%)</sup> | 30.31 | 75.58 | 92.46 |
| **PT** | LLaMA3.1-8B-Instruct | 5.07 | 6.28 | 52.77 | 51.82 |
| **FT**<sup>†</sup> | LLaMA3.1-8B-Instruct | 20.28<sup>(+15.21%)</sup> | 26.13 | 69.44 | 90.43 |
| **FT (ours)** | LLaMA3.1-8B-Instruct | 23.91<sup>(+18.84%)</sup> | 30.36 | 37.96 | 83.23 |
| **RL (ours)** | LLaMA3.1-8B-Instruct | 31.15<sup>(+26.08%)</sup> | 38.03 | 81.28 | <u>95.80</u> |
|  | **ReAct** |  |  |  |  |
| **PT** | Qwen2.5-7B-Instruct | 12.32 | 14.98 | 67.56 | 78.52 |
| **FT**<sup>†</sup> | Qwen2.5-7B-Instruct | 20.28<sup>(+7.96%)</sup> | 27.05 | 35.52 | 62.46 |
| **FT (ours)** | Qwen2.5-7B-Instruct | 30.15<sup>(+17.83%)</sup> | 36.59 | 49.19 | 73.28 |
| **RL (ours)** | Qwen2.5-7B-Instruct | 30.43<sup>(+18.11%)</sup> | 35.20 | <u>102.30</u> | **96.36** |
| **PT** | Qwen3-8B-Instruct | 10.14 | 12.38 | 66.21 | 67.15 |
| **FT**<sup>†</sup> | Qwen3-8B-Instruct | 19.56<sup>(+9.41%)</sup> | 25.60 | 38.69 | 65.18 |
| **FT (ours)** | Qwen3-8B-Instruct | 26.81<sup>(+16.66%)</sup> | 31.09 | 72.16 | 69.85 |
| **RL (ours)** | Qwen3-8B-Instruct | **36.23**<sup>(+26.08%)</sup> | **41.96** | 88.04 | 94.49 |
| **PT** | Qwen3-32B-Instruct | 18.12 | 21.80 | 91.99 | 87.57 |
| **FT**<sup>†</sup> | Qwen3-32B-Instruct | 22.46<sup>(+4.34%)</sup> | 28.20 | 39.28 | 65.50 |
| **FT (ours)** | Qwen3-32B-Instruct | 28.98<sup>(+10.86%)</sup> | 35.92 | 97.79 | 97.33 |
| **RL (ours)** | Qwen3-32B-Instruct | <u>34.78</u><sup>(+16.66%)</sup> | 40.26 | 89.47 | 93.67 |



*<sup>*</sup> LLaMA3.1 models only natively support tool calling w/o reasoning.*  
*<sup>†</sup> The Android Instruct dataset is used for fine-tuning where self-verification is not performed.*  
*<sup>‡</sup> The official results are cited here for comparison.*


---

- **Performance gains**: All model families achieve >16% improvement over prompting baselines, reaching competitive performance with models 10-30× larger.
- **RL dynamics**: Training reward increases consistently while intra-group variance decreases, indicating stable convergence despite occasional performance fluctuations in complex domains (Calendar, Zoom).
- **App-specific analysis**: Dominant improvement in Settings (31% of training tasks) validates the importance of balanced task distribution.

# 📝 Citation

If you use SmartSnap in your research, please cite:

```bibtex
@article{smartsnap2025,
  title={SmartSnap: Proactive Evidence Seeking for Self-Verifying Agents},
  author={Shaofei Cai and Yulei Qin and Haojia Lin and Zihan Xu and Gang Li and Yuchen Shi and Zongyi Li and Yong Mao and Siqi Cai and Xiaoyu Tan and Yitao Liang and Ke Li and Xing Sun},
  journal={arXiv preprint arXiv:2025},
  year={2025},
  eprint={2512.22322},
  url={https://arxiv.org/abs/2512.22322},
}
```

