# pylint: disable=line-too-long, function-name-too-long
import os
import re
import json
import asyncio
from rich import print
from datetime import datetime
from openai import AsyncOpenAI
from svagent.templates.verifier_prompt import SYSTEM_PROMPT_VERIFIER
from svagent.mobile_tool_agent_loop import ToolAgentLoop
from typing import Tuple, List
import numpy as np



def parse_solution_str(solution_str, messages=[]):
    """
    从 solution_str 中解析各种信息
    
    Returns:
        dict: 包含以下字段的字典
        - evidences: list of evidence XML strings
        - valid_evidence: bool or None (从<ValidEvidence>标记解析)
        - verdict: str or None (从<Verdict>标记解析，SUCCESS/FAILURE)
        - last_tool_is_submit: bool (最后一轮工具调用是否为submit)
        - submit_call_count: int (submit工具被调用的次数)
        - submit_message: str or None (submit工具的message参数)
        - submit_evidences: list or None (submit工具的evidences参数)
        - submit_evidences_valid: bool (submit中的evidences下标是否都存在)
        - round_analysis_valid: bool (是否每个tool_call前都有Round X和Analysis)
        - round_sequence_valid: bool (Round X的序号是否按顺序递增)
    """
    result = {
        'evidences': [],
        'valid_evidence': None,
        'verdict': None,
        'last_tool_is_submit': False,
        'submit_call_count': 0,
        'submit_message': None,
        'submit_evidences': None,
        'submit_evidences_valid': False,
        'round_analysis_valid': False,
        'round_sequence_valid': False
    }
    
    # 1. 解析 evidences (tool_response中的XML)
    # 这里需要考虑到不同模型输出 不一定都是<tool_response>...</tool_response>来包裹的
    # tool_response_pattern = r'<tool_response>(.*?)</tool_response>'
    # 用<observation>...</observation>来找是最好的
    if not ("<observation>" in solution_str and "</observation>" in solution_str):
        print("🚨>>> 遇到了没有任何工具调用的输出结果", solution_str)
    tool_response_pattern = r'<observation>(.*?)</observation>'
    tool_responses = re.findall(tool_response_pattern, solution_str, re.DOTALL)
    result['evidences'] = [response.strip() for response in tool_responses]
    
    # 2. 解析 ValidEvidence 标记
    valid_evidence_match = re.search(r'<ValidEvidence>\s*\[?(True|False)\]?\s*</ValidEvidence>', solution_str, re.IGNORECASE)
    if valid_evidence_match:
        result['valid_evidence'] = valid_evidence_match.group(1).lower() == 'true'
    
    # 3. 解析 Verdict 标记
    verdict_match = re.search(r'<Verdict>\s*\[?(SUCCESS|FAILURE)\]?\s*</Verdict>', solution_str, re.IGNORECASE)
    if verdict_match:
        result['verdict'] = verdict_match.group(1).upper()
    
    # 4. 解析工具调用，检查最后一个是否为submit
    parsed_tool_calls_messages = []
    if len(messages):
        for message in messages:
            if "tool_calls" in message:
                tool_calls = message["tool_calls"]
                for tool_call in tool_calls:
                    if type(tool_call) is dict:
                        name = tool_call["function"]["name"]
                        arguments = tool_call["function"]["arguments"]
                    else:
                        name = tool_call.name
                        arguments = tool_call.arguments
                    parsed_tool_calls_messages.append({
                        "name": name,
                        "arguments": arguments,
                    })

    tool_call_pattern = r'<tool_call>\s*(.*?)\s*</tool_call>'
    tool_call_matches = re.findall(tool_call_pattern, solution_str, re.DOTALL)
    
    parsed_tool_calls = []
    for tool_call_str in tool_call_matches:
        try:
            # 使用eval将字符串转换为字典
            tool_call_dict = eval(tool_call_str.strip())
            if isinstance(tool_call_dict, dict) and 'name' in tool_call_dict:
                parsed_tool_calls.append(tool_call_dict)
        except (SyntaxError, NameError, ValueError, TypeError):
            # 如果eval失败，跳过这个工具调用    
            continue
    print("📩 >>> messages: ", messages, ">>> 🛠️ parsed_tool_calls: ", parsed_tool_calls, ">>> 🛠️ parsed_tool_calls_messages: ", parsed_tool_calls_messages)
    if len(parsed_tool_calls) == 0:
        parsed_tool_calls = parsed_tool_calls_messages
    
    if parsed_tool_calls:
        # 统计 submit 工具调用次数
        result['submit_call_count'] = sum(1 for call in parsed_tool_calls if call.get('name') == 'submit')

        # 获取最后一个工具调用的名称
        last_tool_call = parsed_tool_calls[-1]
        result['last_tool_is_submit'] = last_tool_call.get('name') == 'submit'
        
        # 如果最后一个是submit，解析其参数
        if result['last_tool_is_submit']:
            try:
                args = last_tool_call.get('arguments', {})
                if type(args) is str:
                    try:
                        args = json.loads(args)
                    except Exception as e:
                        print(f"loading args {args} for reward calculation failed {e}")
                        args = {}
                result['submit_message'] = args.get('message')
                result['submit_evidences'] = args.get('evidences', [])
                
                # 检查evidences下标是否都存在，并且对应的工具调用不是 'submit'
                if result['submit_evidences']:
                    max_evidence_idx = len(result['evidences']) - 1
                    result['submit_evidences_valid'] = all(
                        isinstance(idx, int) and 0 <= idx <= max_evidence_idx and
                        parsed_tool_calls[idx].get('name') != 'submit'
                        for idx in result['submit_evidences']
                    )
                else:
                    result['submit_evidences_valid'] = False
                    
            except (KeyError, TypeError):
                pass
    
    # 5. 解析Round X和Analysis格式
    result["round_analysis_valid"] = True
    result["round_sequence_valid"] = True
    return result


async def single_verification(bot, messages, model_name, stream, thinking):
    """单次验证函数，带重试机制"""
    max_retries = 3
    retry_delay = 20  # seconds

    last_exception = None
    for attempt in range(max_retries):
        try:
            response_stream = await bot.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.7, 
                stream=stream,
                extra_body={
                    "enable_thinking": thinking, 
                    "chat_template_kwargs": {"thinking": thinking}, 
                    "separate_reasoning": True, 
                }
            )
            response_plain_text = ""
            async for chunk in response_stream:
                if len(chunk.choices) == 0:
                    continue
                if stream and thinking and hasattr(chunk.choices[0].delta, "reasoning_content") and chunk.choices[0].delta.reasoning_content:
                    response_plain_text += chunk.choices[0].delta.reasoning_content
                if stream and chunk.choices[0].delta.content:
                    response_plain_text += chunk.choices[0].delta.content
            
            verdict_match = re.search(r'<Verdict>\s*\[?(SUCCESS|FAILURE)\]?\s*</Verdict>', response_plain_text, re.IGNORECASE)
            valid_evidence_match = re.search(r'<ValidEvidence>\s*\[?(True|False)\]?\s*</ValidEvidence>', response_plain_text, re.IGNORECASE)
            
            success = False
            valid_evidence = False
            
            if verdict_match:
                verdict = verdict_match.group(1).upper()
                success = "SUCCESS" in verdict
            
            if valid_evidence_match:
                evidence_value = valid_evidence_match.group(1).lower()
                valid_evidence = evidence_value == "true"
            
            # 如果成功解析，则直接返回结果
            return success, valid_evidence, response_plain_text

        except Exception as e:
            last_exception = e
            print(f"验证尝试 {attempt + 1}/{max_retries} 失败: {e}")
            if attempt < max_retries - 1:
                print(f"将在 {retry_delay} 秒后重试...")
                await asyncio.sleep(retry_delay)
            else:
                print("已达到最大重试次数，验证失败。")
    
    # 如果所有重试都失败，则抛出最后一次的异常
    raise last_exception



def save_verification_results(save_dir, task_instruction, finish_message, submit_evidences, 
                            messages, model_name, results, N):
    """保存验证结果到指定目录"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    verification_results_dir = os.path.join(save_dir, f"verification_results_{timestamp}")
    os.makedirs(verification_results_dir, exist_ok=True)
    
    # 保存完整的 messages 和每次验证的结果
    verification_data = {
        "task_instruction": task_instruction,
        "finish_message": finish_message,
        "submit_evidences": submit_evidences,
        "messages": messages,
        "model_name": model_name,
        "timestamp": timestamp,
        "verification_results": []
    }
    
    # 统计结果并构建验证数据
    success_count = 0
    valid_evidence_count = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            result_data = {
                "verification_index": i + 1,
                "success": False,
                "exception": str(result),
                "error": True,
                "response_text": None
            }
            print(f"第{i+1}次验证出现异常: {result}")
        else:
            success, valid_evidence, response_text = result
            result_data = {
                "verification_index": i + 1,
                "success": success,
                "valid_evidence": valid_evidence,
                "response_text": response_text,
                "error": False
            }
            if success:
                success_count += 1
            if valid_evidence:
                valid_evidence_count += 1
            print(f"第{i+1}次验证结果: {'SUCCESS' if success else 'FAILURE'}, ValidEvidence: {'True' if valid_evidence else 'False'}")
        
        verification_data["verification_results"].append(result_data)
    
    # 保存验证数据到文件
    verification_file = os.path.join(verification_results_dir, "verification_report.json")
    with open(verification_file, 'w', encoding='utf-8') as f:
        json.dump(verification_data, f, ensure_ascii=False, indent=2)
    
    # 另外保存每个验证的详细响应到单独文件
    for i, result_data in enumerate(verification_data["verification_results"]):
        if not result_data["error"] and result_data["response_text"]:
            response_file = os.path.join(verification_results_dir, f"verification_{i+1}_response.txt")
            with open(response_file, 'w', encoding='utf-8') as f:
                f.write(result_data["response_text"])
    
    print(f"验证结果已保存到: {verification_results_dir}")
    return success_count, valid_evidence_count, verification_results_dir




def compute_score(data_source, solution_str, ground_truth, extra_info=None, **kwargs):
    # ground_truth 表示的是 task instruction
    # solution 是完整的回答
    # extra_info 中包含历史观测、日志目录等信息
    task_config = extra_info['task_config']
    task_instruction = task_config['task_instruction']
    step = extra_info.get("step", None)
    sample_index = extra_info.get("sample_index", None)
    rollout_n = extra_info.get("rollout_n", None)
    validate = extra_info.get("validate", None)
    # save_dir = os.environ.get('MOBILE_SESSION_SAVE_DIR') + "/response_logs"
    save_dir = extra_info["default_local_dir"]
    save_dir = os.path.join(save_dir, "response_logs")
    messages = kwargs["messages"]
    # tools = kwargs["tools"]
    use_toolcall_reward = kwargs["use_toolcall_reward"]
    max_toolcall_steps = kwargs["max_toolcall_steps"]
    global_steps = kwargs["global_steps"]
    if validate is not None and validate:
        save_dir = os.path.join(save_dir, "validation")
    else:
        save_dir = os.path.join(save_dir, "training")
    if step is not None:
        save_dir = os.path.join(save_dir, f"step_{step}")
    # if sample_index and rollout_n:
    #     save_dir = os.path.join(save_dir, f"sample_index_{sample_index}_rollout_n_{rollout_n}")
    os.makedirs(save_dir, exist_ok=True)

    # 保存 solution_str 到 txt 文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    solution_file = os.path.join(save_dir, f"solution_{timestamp}.txt")
    with open(solution_file, 'w', encoding='utf-8') as f:
        f.write(solution_str)

    # 解析 solution_str 中的各种信息
    parsed_info = parse_solution_str(solution_str, messages)
    # 有多少次tool response就对应着多少次tool call
    num_toolcalls = len(parsed_info['evidences'])
    # 初始奖励分数
    total_reward = 0.0
    # 检查基本格式和完成度
    format_penalties = 0.0

    # 1. 检查Round格式
    # if not parsed_info['round_analysis_valid']:
    #     print("惩罚：存在 tool_call 前缺少 Round X 和 Analysis 格式")
    #     format_penalties += 1.0
    
    # if not parsed_info['round_sequence_valid']:
    #     print("惩罚：Round序号不是按顺序递增")
    #     format_penalties += 0.5

    # 2. 检查是否调用了submit工具, 检查submit的evidences参数是否有效
    if parsed_info['submit_call_count'] != 1: 
        format_penalties += 1.0
        print(f"[blue]<X> 惩罚：submit 调用次数 {parsed_info['submit_call_count']} != 1, 奖励: {-format_penalties}[/blue]")
        res = {
            "score": - format_penalties,
            "acc": 0.0,
        }
        return res
    if not parsed_info['last_tool_is_submit']:
        format_penalties += 1.0
        print(f"[blue]<X> 惩罚：最后一轮工具调用不是 submit, 奖励: {-format_penalties}[/blue]")
        res = {
            "score": - format_penalties,
            "acc": 0.0,
        }
        return res
    if not parsed_info['submit_evidences_valid']:
        format_penalties += 1.0
        print(f"[blue]<X> 惩罚：调用 submit 传入的证据参数不对, 奖励: {-format_penalties}[/blue]")
        res = {
            "score": - format_penalties,
            "acc": 0.0,
        }
        return res

    # 构建验证消息
    messages = [{'role': 'user', 'content': SYSTEM_PROMPT_VERIFIER + f"\n## Task Description\n{task_instruction}\n\n## Agent's Final Claim\n{parsed_info['submit_message'] or 'No message provided'}"}]
    
    # 添加evidence到消息中
    for idx in parsed_info['submit_evidences']:
        if 0 <= idx < len(parsed_info['evidences']):
            evidence_content = parsed_info['evidences'][idx]
            messages.append({'role': 'user', 'content': f"** Round {idx} XML Evidence **\n{evidence_content}"})
    
    # model_name="qwen3-235b-a22b"
    model_name = os.environ.get("MODEL_NAME", "DeepSeek-V3.1")
    stream = True
    thinking = True
    if 'r1' in model_name: #! only deepseek-R1 不支持设置 thinking
        thinking = False
    
    # 并行测试 N 次
    N = 3
    async def run_parallel_tests():
        # 使用异步上下文管理器确保客户端正确关闭
        async with AsyncOpenAI(
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"), 
            # base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", 
            # api_key="sk-A7ViN2cT7MXHuzsj0jtXWt6WMe9xqEN77bVgQoW9OfYb0FiQ", 
            # base_url="https://api.kksj.org/v1",
        ) as bot:
            tasks = []
            for i in range(N):
                task = single_verification(bot, messages, model_name, stream, thinking)
                tasks.append(task)
            return await asyncio.gather(*tasks, return_exceptions=True)
    
    # 运行并行测试
    results = asyncio.run(run_parallel_tests())
    
    # 保存验证结果
    success_count, valid_evidence_count, verification_results_dir = save_verification_results(
        save_dir, task_instruction, parsed_info['submit_message'] or 'No message provided', 
        parsed_info['submit_evidences'], messages, model_name, results, N
    )
    # 提交证据的次数作为惩罚; 证据超过3个就给一些惩罚
    evidence_freq_penalties = 0.1 * max(len(parsed_info['submit_evidences']) - 3, 0)  # 证据不宜多 减轻LLM-as-a-Judge压力

    # 计算奖励分数
    cnt_success = 0
    cnt_valid = 0
    no_exception = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            continue
        else:
            success, valid_evidence, response_text = result
            if success:
                cnt_success += 1
            if valid_evidence:
                cnt_valid += 1
            no_exception += 1
    acc = 0.0
    if cnt_success * 2 > no_exception:
        verification_reward = 1.0
        acc = 1.0

    elif cnt_valid * 2 > no_exception:
        verification_reward = 0
    else:
        verification_reward = -1.0

    # 还应该引入tool-call reward
    if verification_reward > 0:
        # 如果是正样本 证据链完整且确凿->仅有无区别
        toolcall_reward = float(num_toolcalls > 0)
    else:
        # 如果是负样本 证据链不完整或不正确
        toolcall_reward = max(min(float(num_toolcalls)*0.1, 1.0), 0.0)
    assert global_steps >= 0
    if use_toolcall_reward == "none":
        res_toolcall_ratio = 0.0
    elif use_toolcall_reward == "constant":
        res_toolcall_ratio = 1
    elif use_toolcall_reward == "cosine":
        res_toolcall_ratio = 1
        if global_steps <= max_toolcall_steps:
            res_toolcall_ratio *= (np.cos((global_steps / max_toolcall_steps) * np.pi) + 1) / 2
        else:
            res_toolcall_ratio = 0
    else:
        raise NotImplementedError("use_toolcall_reward must be one of ['none', 'constant', 'cosine']")
    res_toolcall_ratio = max(res_toolcall_ratio, 0)
    toolcall_reward *= float(res_toolcall_ratio)
    outcome_reward = verification_reward
    final_reward = outcome_reward + toolcall_reward - format_penalties - evidence_freq_penalties

    print(f"🏆🏆🏆<start>\n已评估无异常: {no_exception}, outcome_reward: {verification_reward:.2f}, res_toolcall_ratio: {res_toolcall_ratio:.2f}, toolcall_reward: {toolcall_reward:.2f}, format_penalties: {format_penalties:.2f}, evidence_freq_penalties: {evidence_freq_penalties:.2f}, final_reward: {final_reward:.2f}")
    print(f"解析信息: last_tool_is_submit={parsed_info['last_tool_is_submit']}, "
          f"submit_evidences_valid={parsed_info['submit_evidences_valid']}, "
          f"round_analysis_valid={parsed_info['round_analysis_valid']}, "
          f"round_sequence_valid={parsed_info['round_sequence_valid']}, "
          f"num_toolcalls={num_toolcalls}")
    print(f"[blue]<X> 格式惩罚: {format_penalties:.2f}, 验证奖励: {outcome_reward:.2f}, 最终奖励: {final_reward:.2f}[/blue]")
    print(f"{N}次验证中完全成功{success_count}次，有效证据{valid_evidence_count}次\n<end>🏆🏆🏆")
    
    # return final_reward
    res = {
        "score": final_reward,
        "acc": acc,
    }
    return res
    