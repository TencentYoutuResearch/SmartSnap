# pylint: disable=line-too-long, function-name-too-long
import os
import time
import datetime
import requests
import uuid
import asyncio
import aiohttp
from typing import Optional, Dict, Any, Literal, Union
from dataclasses import dataclass
from copy import deepcopy
from abc import ABC, abstractmethod

from .page_executor import TextOnlyExecutor
from .recorder import JSONRecorder
from .utils_mobile import AndroidController
from .link.connector import RemoteInstance


class DockerManagerInterface(ABC):
    """Docker 管理器抽象接口"""
    
    def __init__(self):
        self.instance_id = None
        self.ip_port = None
    
    @abstractmethod
    def request_instance(self) -> Dict[str, Any]:
        """
        请求一个远程实例
        
        Returns:
            Dict: 包含 success, instance_id, ip_port 等信息的字典
        """
        pass
    
    @abstractmethod
    def release_instance(self) -> Dict[str, Any]:
        """
        释放当前管理的远程实例
        
        Returns:
            Dict: 包含 success 等信息的字典
        """
        pass


class AdvancedDockerManager(DockerManagerInterface):
    """高级 Docker 调度器管理器 - 使用 HTTP API 与 advanced_docker_scheduler 通信"""
    
    def __init__(self, scheduler_url: str, client_id: str = None):
        super().__init__()
        self.scheduler_url = scheduler_url.rstrip('/')  # 去除末尾斜杠
        self.client_id = client_id or f"mobile_session_{int(time.time())}"
    
    def request_instance(self) -> Dict[str, Any]:
        """请求一个远程实例，支持 10 次重试机制"""
        # 由于此方法在同步的 __init__ 中调用，我们使用 asyncio.run 来执行异步逻辑
        return asyncio.run(self._request_instance_async())

    async def _request_instance_async(self) -> Dict[str, Any]:
        """异步请求一个远程实例，支持 503 状态重试"""
        max_retries = 10
        retry_delay_503 = 35  # 503 状态码的重试延迟
        
        async with aiohttp.ClientSession() as session:
            for attempt in range(max_retries):
                print(f"向高级Docker调度器请求远程实例 (尝试 {attempt + 1}/{max_retries}): {self.scheduler_url}")
                
                payload = {'client_id': self.client_id}
                
                try:
                    async with session.post(
                        f"{self.scheduler_url}/allocate", 
                        json=payload,
                        headers={'Content-Type': 'application/json'}
                    ) as response:
                        
                        if response.status == 200:
                            result = await response.json()
                            if result.get('success') and result.get('data'):
                                data = result['data']
                                # 保存实例信息到对象属性
                                self.instance_id = data['instance_id']
                                self.ip_port = data['endpoint']
                                
                                print(f"成功分配实例: {self.instance_id} -> {self.ip_port}")
                                
                                return {
                                    'success': True,
                                    'instance_id': self.instance_id,
                                    'ip_port': self.ip_port
                                }
                            else:
                                error_msg = result.get('error', 'Unknown error')
                                print(f"实例分配失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                        
                        elif response.status == 503:
                            print(f"资源不足 (503)，将在 {retry_delay_503} 秒后重试...")
                            await asyncio.sleep(retry_delay_503)
                            continue  # 直接进入下一次重试
                        
                        else:
                            # 对于其他非 200 和 503 的错误状态码
                            response.raise_for_status()

                except aiohttp.ClientResponseError as e:
                    print(f"HTTP请求失败 (尝试 {attempt + 1}/{max_retries}): {e.status} {e.message}")
                except asyncio.TimeoutError:
                    print(f"请求超时 (尝试 {attempt + 1}/{max_retries}) - 调度器可能正在创建新实例")
                except aiohttp.ClientError as e:
                    print(f"网络或连接错误 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                except Exception as e:
                    print(f"未知错误 (尝试 {attempt + 1}/{max_retries}): {str(e)}")

                # 如果不是因为 503，或者已经是最后一次尝试，则进行常规的递增等待
                if attempt < max_retries - 1:
                    wait_time = 2 * (attempt + 1)
                    print(f"将在 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)

        # 所有尝试都失败后
        return {
            'success': False,
            'error': f'所有 {max_retries} 次尝试都失败'
        }
    
    def release_instance(self) -> Dict[str, Any]:
        """释放当前管理的远程实例"""
        if not self.instance_id:
            return {'success': True, 'message': 'No instance to release'}
            
        try:
            print(f"释放高级Docker调度器实例: {self.instance_id}")
            
            payload = {
                'instance_id': self.instance_id,
                'client_id': self.client_id
            }
            
            response = requests.post(
                f"{self.scheduler_url}/release",
                json=payload,
                headers={'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get('success'):
                print(f"成功释放实例: {self.instance_id}")
                # 清除实例信息
                self.instance_id = None
                self.ip_port = None
                return {'success': True}
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"实例释放失败: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': f'HTTP request failed: {str(e)}'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
        finally:
            # 无论成功与否，都清除本地记录
            self.instance_id = None
            self.ip_port = None


class LegacyDockerManager(DockerManagerInterface):
    """传统 Docker Scheduler 管理器 (已废弃，请使用 AdvancedDockerManager)"""
    
    def __init__(self, scheduler_url: str):
        super().__init__()
        self.scheduler_url = scheduler_url
        print("警告: LegacyDockerManager 已废弃，建议使用 AdvancedDockerManager")
    
    def request_instance(self) -> Dict[str, Any]:
        """请求一个远程实例"""
        try:
            print(f"向传统docker管理器请求远程实例: {self.scheduler_url}")
            
            response = requests.post(f"{self.scheduler_url}/CreateAgentToolEnv", timeout=30)
            result = response.json()
            
            if result.get('success'):
                # 保存实例信息到对象属性
                self.instance_id = result['instance_id']
                self.ip_port = result['ip_port']
                
                return {
                    'success': True,
                    'instance_id': self.instance_id,
                    'ip_port': self.ip_port
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Unknown error')
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def release_instance(self) -> Dict[str, Any]:
        """释放当前管理的远程实例"""
        if not self.instance_id:
            return {'success': True, 'message': 'No instance to release'}
            
        try:
            print(f"释放传统docker实例: {self.instance_id}")
            
            response = requests.post(
                f"{self.scheduler_url}/DeleteAgentToolEnv",
                json={'instance_id': self.instance_id},
                timeout=30
            )
            result = response.json()
            
            if result.get('success'):
                # 清除实例信息
                self.instance_id = None
                self.ip_port = None
                return {'success': True}
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Unknown error')
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
        finally:
            # 无论成功与否，都清除本地记录
            self.instance_id = None
            self.ip_port = None


class TioneDockerManager(DockerManagerInterface):
    """Tione Docker 管理器"""
    
    def __init__(self, env_type: str = "OS", image_info: dict = None):
        super().__init__()
        # 延迟导入，避免在不使用 Tione 时的依赖问题
        from .docker_client_tione import TioneEnvManager
        self.manager = TioneEnvManager(type=env_type, image_info=image_info)
    
    def request_instance(self) -> Dict[str, Any]:
        """请求一个远程实例"""
        try:
            print("向 Tione 管理器请求远程实例")
            
            # 使用 asyncio 运行异步方法
            result = asyncio.run(self.manager.create_env())
            
            # 保存实例信息到对象属性
            self.instance_id = result['env_id']
            self.ip_port = result['endpoint']
            
            return {
                'success': True,
                'instance_id': self.instance_id,
                'ip_port': self.ip_port
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def release_instance(self) -> Dict[str, Any]:
        """释放当前管理的远程实例"""
        if not self.instance_id:
            return {'success': True, 'message': 'No instance to release'}
            
        try:
            print(f"释放 Tione 实例: {self.instance_id}")
            asyncio.run(self.manager.delete_env(self.instance_id))
            # 清除实例信息
            self.instance_id = None
            self.ip_port = None
            
            return {'success': True}
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
        finally:
            # 无论成功与否，都清除本地记录
            self.instance_id = None
            self.ip_port = None


class MobileSession:
    """
    MobileSession 类用于管理移动自动化会话中的三个核心组件：
    - page_executor: 页面执行器，负责UI界面的交互操作
    - recorder: 记录器，负责记录操作过程和结果
    - controller: Android控制器，负责设备的底层控制
    - instance: 设备实例，负责管理模拟器或设备连接
    """
    
    def __init__(self, 
                 task_dict: Dict[str, Any], 
                 config: Dict[str, Any], 
                 docker_manager: DockerManagerInterface,
                 save_dir: str = "./output"):
        """
        初始化 MobileSession
        
        Args:
            task_dict: 任务字典，包含task_id, task_instruction, app等信息
            config: 配置字典，包含各种设置参数
            docker_manager: Docker 管理器实例，实现 DockerManagerInterface 接口
            save_dir: 保存目录
        """
        # 从 task_dict 中提取信息
        task_id = task_dict.get('task_id', 'unknown_task')
        self.app = task_dict.get('app', '')
        if not (self.app in task_id):
            task_id = str(self.app) + f"_{task_id}"
        demo_timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]  # 使用UUID的前8位作为唯一标识
        self.task_name = (task_id + "_" + datetime.datetime.fromtimestamp(demo_timestamp).strftime("%Y-%m-%d_%H-%M-%S") + "_" + unique_id).replace(" ", "_")
        self.instruction = task_dict.get('task_instruction', '')
        self.command_per_step = task_dict.get('command_per_step', None)
        self.llm_agent = task_dict.get('agent', None)
        self.config = deepcopy(config)

        self.controller_type = "remote"  # 固定为 remote
        self.instance_type = "remote"    # 固定为 remote
        self.save_dir = save_dir
        
        # 设置 Docker 管理器
        self.docker_manager = docker_manager
        self.docker_manager_type = type(docker_manager).__name__  # 记录管理器类型名称
        
        self.device = None
        # 核心组件
        self._instance = None
        self._controller = None
        self._page_executor = None
        self._recorder = None
        
        # 清理状态标志
        self._cleaned_up = False
        
        # 准备任务目录结构
        self._prepare_for_task()
        
        # 向 docker 管理器请求一个远程实例
        self.docker_instance_id = None
        self.docker_ip_port = None
        self._request_docker_instance()
        
        # 初始化组件
        self._initialize_components()

    def _prepare_for_task(self):
        """
        准备任务目录结构，复刻 AutoTest.prepare_for_task 的逻辑
        """
        # 创建保存目录
        os.makedirs(self.save_dir, exist_ok=True)
        
        # 设置任务相关路径
        self.config['task_dir'] = os.path.join(self.save_dir, self.task_name)
        self.config['log_path'] = os.path.join(self.config['task_dir'], f"log_explore_{self.task_name}.jsonl")
        self.config['trace_dir'] = os.path.join(self.config['task_dir'], 'traces')
        self.config['screenshot_dir'] = os.path.join(self.config['task_dir'], 'Screen')
        self.config['xml_dir'] = os.path.join(self.config['task_dir'], 'xml')
        
        # 创建目录
        os.makedirs(self.config['task_dir'], exist_ok=True)
        os.makedirs(self.config['trace_dir'], exist_ok=True)
        os.makedirs(self.config['screenshot_dir'], exist_ok=True)
        os.makedirs(self.config['xml_dir'], exist_ok=True)
    
    def _request_docker_instance(self):
        """
        向docker管理器请求一个远程实例
        """
        try:
            result = self.docker_manager.request_instance()
            
            if result.get('success'):
                self.docker_instance_id = result['instance_id']
                self.docker_ip_port = result['ip_port']
                
                # 解析IP和端口
                if ':' in self.docker_ip_port:
                    ip, port = self.docker_ip_port.split(':')
                    self.config['remote_ip'] = ip
                    self.config['remote_port'] = int(port)
                
                print(f"成功获取docker实例: {self.docker_instance_id} -> {self.docker_ip_port}")
                
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"Warning: 无法获取docker实例: {error_msg}")
                
        except Exception as e:
            print(f"Warning: 请求docker实例时出错: {e}")
            # 如果请求失败，使用默认的远程连接配置
            print("将使用默认的远程连接配置")
    
    def _create_instance(self):
        """创建远程实例"""
        # 优先使用从docker管理器获取的远程连接信息
        if self.docker_ip_port and ':' in self.docker_ip_port:
            # 如果成功从docker管理器获取了实例，使用该IP和端口
            ip, port = self.docker_ip_port.split(':')
            remote_ip = ip
            remote_port = int(port)
            print(f"使用docker管理器分配的连接信息: {remote_ip}:{remote_port}")
        else:
            # 否则使用配置中的默认值
            remote_ip = self.config.get("remote_ip", "localhost")
            remote_port = self.config.get("remote_port", 6060)
            print(f"使用配置中的默认连接信息: {remote_ip}:{remote_port}")
        
        return RemoteInstance(
            config=self.config, 
            remote_ip=remote_ip,
            remote_port=remote_port
        )
    
    def get_evidences_str(self, evidences: list[int]) -> list[str]:
        """
        获取 compressed_xml 类型的证据
        """
        xml_dir = self.config.get('xml_dir')
        outputs = []
        for idx in evidences:
            xml_path = os.path.join(xml_dir, f"{idx}_compressed_xml.txt")
            if os.path.exists(xml_path):
                with open(xml_path, 'r', encoding='utf-8') as f:
                    xml_content = f.read()
                outputs.append(xml_content)
            else:
                outputs.append("ERROR: File not found")
        return outputs
    
    def _start_device_internal(self):
        """
        内部设备启动逻辑，返回设备名称
        
        Returns:
            str: 设备名称，如果启动失败返回 None
        """
        if not self._instance:
            print("Warning: Instance not initialized")
            return None
            
        if self.device:
            print(f"设备已启动: {self.device}")
            return self.device
        
        try:
            print("正在启动设备/模拟器...")
            # 调用 instance.initialize_single_task 启动设备并获取设备名称
            device = self._instance.initialize_single_task(self.config)
            self.device = device
            print(f"设备启动成功: {device}")
            return device
            
        except Exception as e:
            print(f"Warning: Could not initialize device: {e}")
            return None

    def _initialize_components(self):
        """
        初始化所有核心组件，复刻 AutoTest.run_task 和 AutoTest.start_emulator 的逻辑
        """
        # 1. 初始化 instance
        self._instance = self._create_instance()
        
        # 2. 启动设备/模拟器并获取设备名称（复刻 AutoTest.start_emulator 逻辑）
        device = self._start_device_internal()
        if not device:
            # 如果设备启动失败，保持 instance 但不创建其他组件
            return
        
        # 3. 初始化 controller（需要 device 和 instance）
        if self.device and self._instance:
            self._controller = AndroidController(
                device=self.device, 
                type=self.controller_type,
                instance=self._instance
            )
            
            # 执行设备初始化命令（复刻 AutoTest.start_emulator 的设备设置逻辑）
            self._setup_device_commands()
        
        # 4. 初始化 page_executor（需要 controller）
        if self._controller:
            self._page_executor = TextOnlyExecutor(
                controller=self._controller,
                config=self.config
            )
        
        # 5. 初始化 recorder（需要 page_executor）
        if self._page_executor:
            self._recorder = JSONRecorder(
                id=self.task_name,
                instruction=self.instruction or "",
                page_executor=self._page_executor,
                config=self.config
            )
    
    def _setup_device_commands(self):
        """
        执行设备初始化命令，复刻 AutoTest.start_emulator 的设备设置逻辑
        """
        if not self.device or not self._instance or not self._controller:
            return
        
        try:
            # 执行设备初始化命令（复刻 AutoTest.start_emulator 的逻辑）
            self._controller.run_command("adb root")
            self._controller.run_command("adb emu geo fix -122.156 37.438")
            
            # 设置时间（除非是特定应用）
            if self.instruction and "map.me" not in self.instruction:
                self._controller.run_command("adb shell date \"2024-05-10 12:00:00\"")
            
            # 如果配置为应用内模式，启动应用
            if self.config.get('mode') == "in_app" and self.app:
                from .templates.packages import find_package
                self._controller.launch_app(find_package(self.app))
                time.sleep(15)
                
            print("设备初始化命令执行完成")
            
        except Exception as e:
            print(f"Warning: Device setup commands failed: {e}")

    def stop_device(self):
        """停止设备/模拟器"""
        if self._instance:
            self._instance.stop_single_task()
            self.device = None

    @property
    def instance(self) -> Optional[object]:
        """获取设备实例"""
        return self._instance

    @property
    def controller(self) -> Optional[AndroidController]:
        """获取 Android 控制器"""
        return self._controller

    @property
    def page_executor(self) -> Optional[TextOnlyExecutor]:
        """获取页面执行器"""
        return self._page_executor

    @property
    def recorder(self) -> Optional[JSONRecorder]:
        """获取记录器"""
        return self._recorder

    def setup_device(self, device: str, controller_type: str = None, auto_reinitialize: bool = True):
        """
        设置设备并重新初始化组件
        
        Args:
            device: Android设备标识符
            controller_type: 控制器类型，如果为None则保持当前类型
            auto_reinitialize: 是否自动重新初始化组件
        """
        self.device = device
        if controller_type:
            self.controller_type = controller_type
        
        if auto_reinitialize:
            self._initialize_components()

    def update_task_info(self, task_name: str = None, instruction: str = None):
        """
        更新任务信息
        
        Args:
            task_name: 新的任务名称
            instruction: 新的任务指令
        """
        if task_name:
            self.task_name = task_name
        if instruction:
            self.instruction = instruction
        
        # 重新初始化 recorder 以使用新的任务信息
        if self._page_executor:
            self._recorder = JSONRecorder(
                id=self.task_name,
                instruction=self.instruction or "",
                page_executor=self._page_executor,
                config=self.config
            )

    def update_config(self, config: Dict[str, Any], auto_reinitialize: bool = True):
        """
        更新配置并重新初始化相关组件
        
        Args:
            config: 新的配置字典
            auto_reinitialize: 是否自动重新初始化组件
        """
        self.config.update(config)
        
        if auto_reinitialize:
            # 重新初始化组件以应用新配置
            self._initialize_components()

    def is_ready(self) -> bool:
        """
        检查会话是否准备就绪（所有核心组件都已初始化）
        
        Returns:
            bool: True表示所有组件都已就绪，False表示有组件未初始化
        """
        return all([
            self._instance is not None,
            self._controller is not None,
            self._page_executor is not None,
            self._recorder is not None
        ])

    def is_device_ready(self) -> bool:
        """
        检查设备是否已启动并准备就绪
        
        Returns:
            bool: True表示设备已启动，False表示设备未启动
        """
        return self.device is not None and self.is_ready()

    def get_session_info(self) -> Dict[str, Any]:
        """
        获取会话信息
        
        Returns:
            Dict: 包含会话相关信息的字典
        """
        return {
            "device": self.device,
            "task_name": self.task_name,
            "instruction": self.instruction,
            "app": getattr(self, 'app', None),
            "controller_type": self.controller_type,
            "instance_type": self.instance_type,
            "is_ready": self.is_ready(),
            "is_device_ready": self.is_device_ready(),
            "docker_info": {
                "manager_type": self.docker_manager_type,
                "instance_id": self.docker_instance_id,
                "ip_port": self.docker_ip_port,
            },
            "config_paths": {
                "task_dir": self.config.get('task_dir'),
                "log_path": self.config.get('log_path'),
                "trace_dir": self.config.get('trace_dir'),
                "screenshot_dir": self.config.get('screenshot_dir'),
                "xml_dir": self.config.get('xml_dir')
            },
            "components": {
                "instance": self._instance is not None,
                "controller": self._controller is not None,
                "page_executor": self._page_executor is not None,
                "recorder": self._recorder is not None
            }
        }
    
    def _release_docker_instance(self):
        """
        释放docker实例
        """
        if self.docker_instance_id:
            try:
                print(f"释放docker实例: {self.docker_instance_id}")
                
                result = self.docker_manager.release_instance()
                
                if result.get('success'):
                    print(f"成功释放docker实例: {self.docker_instance_id}")
                else:
                    print(f"Warning: 释放docker实例失败: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                print(f"Warning: 释放docker实例时出错: {e}")
            
            finally:
                # 无论是否成功释放，都清除本地记录
                self.docker_instance_id = None
                self.docker_ip_port = None
    
    def cleanup(self):
        """
        清理资源（如果组件有清理方法的话）
        """
        # 防止重复清理
        if self._cleaned_up:
            print("资源已清理，跳过重复清理")
            return
        
        try:
            # 停止设备
            # try:
            #     self.stop_device()
            # except Exception as e:
            #     print(f"Warning: Error stopping device: {e}")
            
            # 释放docker实例
            self._release_docker_instance()
            pass
        finally:
            # 标记为已清理，防止重复清理
            self._cleaned_up = True
    
    @classmethod
    def from_task_dict(cls, task_dict: Dict[str, Any], config: Dict[str, Any], **kwargs):
        """
        从 task_dict 创建 MobileSession 实例的便捷方法（与直接调用构造函数等效）
        
        Args:
            task_dict: 任务字典，包含task_id, task_instruction, app等信息
            config: 配置字典
            **kwargs: 其他传递给 __init__ 的参数
        
        Returns:
            MobileSession: 新创建的会话实例
        """
        return cls(task_dict=task_dict, config=config, **kwargs)
    
    def run_task_setup(self):
        """
        执行任务设置，相当于 AutoTest.run_task 的初始化部分
        这个方法假设实例已经通过 task_dict 初始化
        """
        if not hasattr(self, 'instruction') or not self.instruction:
            raise ValueError("Task instruction is required for task setup")
        
        # 启动设备并设置
        self.start_device(auto_initialize=True, setup_device=True)
        
        # 所有组件现在应该都已就绪
        if not self.is_ready():
            raise Exception("Failed to initialize all components")
        
        print(f"Task setup completed for: {self.instruction}")
        return True
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口，确保资源清理"""
        self.cleanup()
    
    def __del__(self):
        """析构函数，确保资源清理"""
        try:
            self.cleanup()
        except:
            pass