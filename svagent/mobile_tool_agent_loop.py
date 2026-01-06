# pylint: disable=line-too-long, function-name-too-long
# Copyright 2024 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import asyncio
import json
import logging
import os
import copy
import numpy as np
from typing import Any
from uuid import uuid4
import time
from verl.experimental.agent_loop.agent_loop import AgentLoopBase, AgentLoopOutput, register
from verl.experimental.agent_loop.tool_parser import FunctionCall, ToolParser
from verl.tools.utils.tool_registry import initialize_tools_from_config
from verl.utils.profiler import simple_timer
from verl.utils.rollout_trace import rollout_trace_op
from .mobile_session import MobileSession

logger = logging.getLogger(__file__)
logger.setLevel(os.getenv("VERL_LOGGING_LEVEL", "WARN"))


@register("mobile_tool_agent")
class ToolAgentLoop(AgentLoopBase):
    @classmethod
    def init_class(cls, config, tokenizer, **kwargs):
        if cls._class_initialized:
            return
        cls._class_initialized = True
        print("Performing class-level ToolAgentLoop initialization")

        # Initialize tools from config file
        cls.tokenizer = tokenizer
        cls.max_user_turns = config.actor_rollout_ref.rollout.multi_turn.max_user_turns
        cls.max_assistant_turns = config.actor_rollout_ref.rollout.multi_turn.max_assistant_turns
        cls.max_parallel_calls = config.actor_rollout_ref.rollout.multi_turn.max_parallel_calls
        cls.max_tool_response_length = config.actor_rollout_ref.rollout.multi_turn.max_tool_response_length
        cls.tool_response_truncate_side = config.actor_rollout_ref.rollout.multi_turn.tool_response_truncate_side
        tool_config_path = config.actor_rollout_ref.rollout.multi_turn.tool_config_path
        try:
            tool_list = initialize_tools_from_config(tool_config_path) if tool_config_path else []
        except Exception as e:
            print(f"Initialize Tool calls from {tool_config_path} failed with {e} for the first time")
            try:
                tool_list = initialize_tools_from_config(tool_config_path) if tool_config_path else []
            except Exception as e:
                print(f"Initialize Tool calls from {tool_config_path} failed with {e} for the second time")
                tool_list = []
        cls.tools = {tool.name: tool for tool in tool_list}
        cls.tool_schemas = [tool.tool_schema.model_dump(exclude_unset=True, exclude_none=True) for tool in tool_list]
        cls.tool_parser = ToolParser.get_tool_parser(config.actor_rollout_ref.rollout.multi_turn.format, cls.tokenizer)
        print(f"Initialized tools: {cls.tools}")
        print(f"Initialzed tool schemas: {cls.tool_schemas}")
        cls.prompt_length = config.actor_rollout_ref.rollout.prompt_length
        cls.response_length = config.actor_rollout_ref.rollout.response_length
        try:
            cls.system_prompt = tokenizer.apply_chat_template([{}], add_generation_prompt=False, tokenize=True)
        except:
            # 以防某些tokenizer不支持传入空模板来获取默认system prompt->llama
            system_prompt = tokenizer.apply_chat_template([{"role": "user", "content": ""}], add_generation_prompt=False, tokenize=False)
            system_prompt = system_prompt[:system_prompt.rfind("user")]
            system_prompt = system_prompt[:system_prompt.rfind(tokenizer.eos_token)+len(tokenizer.eos_token)]
            system_prompt_tkid = tokenizer.encode(system_prompt, add_special_tokens=False)
            cls.system_prompt = system_prompt_tkid
        print(f"Sytem prompt for the tokenizer\n>>>>>> start of the system prompt <<<<<<\n\n{cls.system_prompt}\n\n>>>>>> end of the system prompt <<<<<<")

    @rollout_trace_op
    async def run(self, messages: list[dict[str, Any]], sampling_params: dict[str, Any], **kwargs) -> AgentLoopOutput:
        metrics = {}
        request_id = uuid4().hex
        assert(len(self.tool_schemas) > 0)
        prompt_ids = await self.loop.run_in_executor(
            None,
            lambda: self.tokenizer.apply_chat_template(
                messages, tools=self.tool_schemas, add_generation_prompt=True, tokenize=True
            ),
        )
        prompt_text = await self.loop.run_in_executor(
            None,
            lambda: self.tokenizer.apply_chat_template(
                messages, tools=self.tool_schemas, add_generation_prompt=True, tokenize=False
            ),
        )
        print(f">>>🐳 {prompt_text=}")
        response_mask = []
        step = kwargs.get("step", None)
        sample_index = kwargs.get("sample_index", None)
        rollout_n = kwargs.get("rollout_n", None)
        validate = kwargs.get("validate", None)
        
        #! [START] Initialize mobile session if needed [added by caishaofei]
        # Create deep copies to ensure each sample has independent configs
        mobile_config = copy.deepcopy(kwargs.get("extra_info", {}).get("mobile_config", {}))
        task_config = copy.deepcopy(kwargs.get("extra_info", {}).get("task_config", {}))

        # Convert numpy arrays to OmegaConf format
        if mobile_config is not None and isinstance(mobile_config, np.ndarray):
            # Assuming the numpy array contains serialized data that needs to be converted
            mobile_config = OmegaConf.create(mobile_config.item() if mobile_config.ndim == 0 else mobile_config.tolist())
        if task_config is not None and isinstance(task_config, np.ndarray):
            # Assuming the numpy array contains serialized data that needs to be converted
            task_config = OmegaConf.create(task_config.item() if task_config.ndim == 0 else task_config.tolist())
        
        if mobile_config is not None and isinstance(mobile_config, dict):
            app_name_mobile = (mobile_config.get("app_name", "")).lower()
        else:
            app_name_mobile = ""
        if task_config is not None and isinstance(task_config, dict):
            app_name_task = (task_config.get("app", "")).lower()
        else:
            app_name_task = ""
        print(f"{app_name_mobile=}, {app_name_task=}")
        assert(not (app_name_mobile=="" and app_name_task==""))
        # Use environment variable to override save_dir if provided
        # assert "MOBILE_SESSION_SAVE_DIR" in os.environ, "Environment variable MOBILE_SESSION_SAVE_DIR must be set"
        # save_dir = os.getenv("MOBILE_SESSION_SAVE_DIR")
        save_dir = os.path.join(kwargs["default_local_dir"], "mobile_output")
        if validate is not None and validate:
            save_dir = os.path.join(save_dir, "validation")
        else:
            save_dir = os.path.join(save_dir, "training")
        if step is not None:
            save_dir = os.path.join(save_dir, f"step_{step}")
        # if sample_index and rollout_n:
        #     save_dir = os.path.join(save_dir, f"sample_index_{sample_index}_rollout_n_{rollout_n}")
        os.makedirs(save_dir, exist_ok=True)
        # Create Docker manager based on environment configuration
        docker_manager_type = os.getenv("DOCKER_MANAGER_TYPE", "tione")  # Default to Tione
        logger.info(f"[DEBUG] Using docker manager type: {docker_manager_type}")
        
        if docker_manager_type.lower() == "advanced":
            # Use legacy Docker Scheduler manager
            assert "DOCKER_SCHEDULER_URL" in os.environ, "Environment variable DOCKER_SCHEDULER_URL must be set when using legacy manager"
            docker_scheduler_url = os.getenv("DOCKER_SCHEDULER_URL")
            logger.info(f"[DEBUG] Creating AdvancedDockerManager with URL: {docker_scheduler_url}")
            from .mobile_session import AdvancedDockerManager
            docker_manager = AdvancedDockerManager(scheduler_url=docker_scheduler_url)
        else:
            # Use Tione Docker manager (default)
            from .mobile_session import TioneDockerManager
            env_type = os.getenv("TIONE_ENV_TYPE", "OS")  # Default environment type
            logger.info(f"[DEBUG] Creating TioneDockerManager with env_type: {env_type}")
            docker_manager = TioneDockerManager(env_type=env_type)

        mobile_session = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: MobileSession(
                task_dict=task_config, 
                config=mobile_config, 
                docker_manager=docker_manager, 
                save_dir=save_dir
            )
        )
        if ("map.me" in app_name_mobile) or ("maps.me" in app_name_mobile) or ("pimusic" in app_name_mobile) or \
            ("map.me" in app_name_task) or ("maps.me" in app_name_task) or ("pimusic" in app_name_task):
            accessibility = mobile_session._controller.check_ac_survive()
        else:
            accessibility = False
        create_kwargs = dict(
            mobile_session=mobile_session,
            accessibility=accessibility,
        )
        time.sleep(5)
        user_turns, assistant_turns = 0, 0
        task_done = False
        messages_full = {"tools": self.tool_schemas, "messages": copy.deepcopy(messages)}

        while True:
            with simple_timer("generate_sequences", metrics):
                response_ids = await self.server_manager.generate(
                    request_id=request_id, prompt_ids=prompt_ids, sampling_params=sampling_params
                )
            prompt_ids += response_ids
            response_mask += [1] * len(response_ids)
            assistant_turns += 1

            # reach max response length
            if len(response_mask) >= self.response_length:
                break

            # reach max assistant turns
            if self.max_assistant_turns and assistant_turns >= self.max_assistant_turns:
                break

            # reach max user turns
            if self.max_user_turns and user_turns >= self.max_user_turns:
                break

            # no tool calls
            assistant_content, tool_calls = await self.tool_parser.extract_tool_calls(response_ids)
            messages_full["messages"].append(
                {"role": "assistant", "content": copy.deepcopy(assistant_content), "tool_calls": copy.deepcopy(tool_calls)}
            )
            if not tool_calls:
                break

            # call tools
            tasks = []
            for tool_call in tool_calls[: self.max_parallel_calls]:
                tasks.append(self._call_tool(tool_call, create_kwargs=create_kwargs, assistant_turns_index=assistant_turns-1))
            with simple_timer("tool_calls", metrics):
                tool_responses = await asyncio.gather(*tasks)
            if any(isinstance(item, Exception) for item in tool_responses):
                break
            messages_full["messages"] += tool_responses
            # append tool_response_ids
            tool_response_ids = await self.loop.run_in_executor(
                None,
                lambda messages=tool_responses: self.tokenizer.apply_chat_template(
                    messages, add_generation_prompt=True, tokenize=True
                ),
            )
            tool_response_ids = tool_response_ids[len(self.system_prompt) :]
            # NOTE: last turn should not be user turn, or the EOS token reward
            # can't be propagated to previous token in GAE.
            if len(response_mask) + len(tool_response_ids) >= self.response_length:
                break

            prompt_ids += tool_response_ids
            response_mask += [0] * len(tool_response_ids)
            user_turns += 1
            # 判断是否出现了submit调用 从而简化流程
            for tool_call in tool_calls:
                if tool_call.name == "submit":
                    task_done = True
                    break

            if task_done:
                break

        response_ids = prompt_ids[-len(response_mask) :]
        prompt_ids = prompt_ids[: len(prompt_ids) - len(response_mask)]
        mobile_session._release_docker_instance()
        output = AgentLoopOutput(
            prompt_ids=prompt_ids,
            response_ids=response_ids[: self.response_length],
            response_mask=response_mask[: self.response_length],
            num_turns=user_turns + assistant_turns + 1,
            metrics=metrics,
            messages=messages_full,
        )
        return output

    async def _call_tool(self, tool_call: FunctionCall,\
        create_kwargs: dict[str, Any], assistant_turns_index: int) -> dict[str, str]:
        """Call tool and return tool response."""
        tool, instance_id = None, None
        try:
            # TODO: append malformed tool_call to the prompt: invalid function name or arguments
            tool_name = tool_call.name
            arguments = tool_call.arguments
            tool = self.tools[tool_name]
            instance_id = await tool.create(create_kwargs=create_kwargs)
            tool_response, _, _ = await tool.execute(instance_id, arguments)
        except Exception as e:
            logger.exception(f"Error when executing tool: {e}")
            return e
        finally:
            if tool and instance_id:
                await tool.release(instance_id)

        if len(tool_response) > self.max_tool_response_length:
            if self.tool_response_truncate_side == "left":
                tool_response = tool_response[: self.max_tool_response_length] + "...(truncated)"
            elif self.tool_response_truncate_side == "right":
                tool_response = "(truncated)..." + tool_response[-self.max_tool_response_length :]
            else:
                length = self.max_tool_response_length // 2
                tool_response = tool_response[:length] + "...(truncated)..." + tool_response[-length:]
        tool_response_round = f"## Round {assistant_turns_index}\n{tool_response}"
        tool_response_start_tag = "<observation>\n"
        tool_response_end_tag = "\n</observation>"
        return {
            "role": "tool",
            "content": tool_response_start_tag+tool_response_round+tool_response_end_tag,
        }




