# pylint: disable=line-too-long, function-name-too-long
import time
import requests
import json
import base64
import os
from ..utils_mobile.utils import print_with_color


class RemoteInstance:
    """
    RemoteInstance 类用于通过 IP 和端口与远程 Android 设备的 ADB 客户端进行交互。
    这个类仿照 DockerInstance 的结构，但不依赖 Docker 容器，而是直接连接到远程服务。
    """
    
    def __init__(self, config, remote_ip="localhost", remote_port=6060):
        """
        初始化 RemoteInstance
        
        Args:
            config: 配置对象
            remote_ip: 远程服务器 IP 地址
            remote_port: 远程服务器端口
        """
        self.config = config
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.base_url = f"http://{remote_ip}:{remote_port}"
        self.device = None
        self.initialize_worker(config)

    def initialize_worker(self, config):
        """
        初始化工作器，设置配置
        """
        self.config = config
        print_with_color(f"Initializing remote connection to {self.remote_ip}:{self.remote_port}", "blue")
        
    def initialize_single_task(self, config):
        """
        初始化单个任务，启动远程 AVD 并返回设备名称
        
        Args:
            config: 任务配置
            
        Returns:
            str: 设备名称
        """
        print_with_color(f"Starting Android Emulator on remote server with AVD name: {config.get('avd_name', 'default')}", "blue")
        
        avd_name = config.get('avd_name', 'default')
        
        # 启动远程 AVD
        result = self._start_remote_avd(avd_name)
        if not result or "error" in result:
            raise Exception(f"Failed to start remote AVD: {result}")
            
        device = result.get("device")
        if not device:
            raise Exception("No device returned from remote AVD start")
            
        self.device = device
        print("Device name: ", device)
        print("AVD name: ", avd_name)

        # 创建必要的目录
        # self._create_remote_directories(config)
        
        # 等待设备完全启动
        time.sleep(10)
        
        return device

    def stop_single_task(self):
        """
        停止单个任务，关闭远程 AVD
        """
        print_with_color("Stopping Android Emulator on remote server...", "blue")
        
        if self.device and self.config.get('avd_name'):
            try:
                result = self._stop_remote_avd(self.config.get('avd_name'))
                if result and "error" not in result:
                    print_with_color("Remote emulator stopped successfully", "blue")
                else:
                    print_with_color(f"Warning: Error stopping remote emulator: {result}", "yellow")
            except Exception as e:
                print_with_color(f"Warning: Exception while stopping remote emulator: {e}", "yellow")
        
        self.device = None

    def _start_remote_avd(self, avd_name):
        """
        启动远程 AVD
        
        Args:
            avd_name: AVD 名称
            
        Returns:
            dict: 启动结果
        """
        url = f'{self.base_url}/start'
        headers = {'Content-Type': 'application/json'}
        data = {'avd_name': avd_name}
        
        return self._send_post_request(url, headers, data)

    def _stop_remote_avd(self, avd_name):
        """
        停止远程 AVD
        
        Args:
            avd_name: AVD 名称
            
        Returns:
            dict: 停止结果
        """
        url = f'{self.base_url}/stop'
        headers = {'Content-Type': 'application/json'}
        data = {'avd_name': avd_name}
        
        return self._send_post_request(url, headers, data)

    def execute_remote_adb_command(self, command):
        """
        在远程服务器上执行 ADB 命令
        
        Args:
            command: ADB 命令
            
        Returns:
            dict: 命令执行结果
        """
        url = f'{self.base_url}/execute'
        headers = {'Content-Type': 'application/json'}
        data = {'command': command}
        
        return self._send_post_request(url, headers, data)

    def pull_file_from_device(self, remote_path, local_path):
        """
        从远程 Android 设备拉取文件到本地
        
        Args:
            remote_path: 设备上的文件路径
            local_path: 本地保存路径
            
        Returns:
            bool: 是否成功
        """
        try:
            url = f'{self.base_url}/pull_file'
            headers = {'Content-Type': 'application/json'}
            data = {
                'device': self.device,
                'remote_path': remote_path
            }
            
            result = self._send_post_request(url, headers, data)
            
            if result and result.get('result') == 'success':
                # 解码 base64 内容并保存到本地文件
                file_content = base64.b64decode(result['file_content'])
                
                # 确保本地目录存在
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                
                with open(local_path, 'wb') as f:
                    f.write(file_content)
                
                print_with_color(f"File pulled successfully: {remote_path} -> {local_path}", "green")
                return True
            else:
                print_with_color(f"Failed to pull file: {result}", "red")
                return False
                
        except Exception as e:
            print_with_color(f"Error pulling file: {e}", "red")
            return False

    def push_file_to_device(self, local_path, remote_path):
        """
        将本地文件推送到远程 Android 设备
        
        Args:
            local_path: 本地文件路径
            remote_path: 设备上的目标路径
            
        Returns:
            bool: 是否成功
        """
        try:
            if not os.path.exists(local_path):
                print_with_color(f"Local file does not exist: {local_path}", "red")
                return False
            
            # 读取本地文件并编码为 base64
            with open(local_path, 'rb') as f:
                file_content = f.read()
                file_base64 = base64.b64encode(file_content).decode('utf-8')
            
            url = f'{self.base_url}/push_file'
            headers = {'Content-Type': 'application/json'}
            data = {
                'device': self.device,
                'remote_path': remote_path,
                'file_content': file_base64
            }
            
            result = self._send_post_request(url, headers, data)
            
            if result and result.get('result') == 'success':
                print_with_color(f"File pushed successfully: {local_path} -> {remote_path}", "green")
                return True
            else:
                print_with_color(f"Failed to push file: {result}", "red")
                return False
                
        except Exception as e:
            print_with_color(f"Error pushing file: {e}", "red")
            return False

    def list_device_files(self, directory="/sdcard"):
        """
        列出设备上指定目录的文件
        
        Args:
            directory: 目录路径
            
        Returns:
            list: 文件列表
        """
        try:
            url = f'{self.base_url}/list_files'
            headers = {'Content-Type': 'application/json'}
            data = {
                'device': self.device,
                'directory': directory
            }
            
            result = self._send_post_request(url, headers, data)
            
            if result and result.get('result') == 'success':
                return result.get('files', [])
            else:
                print_with_color(f"Failed to list files: {result}", "red")
                return []
                
        except Exception as e:
            print_with_color(f"Error listing files: {e}", "red")
            return []

    def _send_post_request(self, url, headers, data, max_attempts=30, retry_interval=30, timeout=300):
        """
        发送 POST 请求到远程服务器
        
        Args:
            url: 请求 URL
            headers: 请求头
            data: 请求数据
            max_attempts: 最大重试次数
            retry_interval: 重试间隔（秒）
            timeout: 请求超时时间（秒）
            
        Returns:
            dict: 响应数据
        """
        attempts = 0
        while attempts < max_attempts:
            try:
                response = requests.post(url, headers=headers, data=json.dumps(data), timeout=timeout)
                return response.json()
            except Exception as e:
                print_with_color(f"Error occurred while sending request to {url}: {e}", "red")
                attempts += 1
                if attempts < max_attempts:
                    print_with_color(f"Timeout occurred. Retrying... Attempt {attempts}/{max_attempts}", "yellow")
                    print(f"Request data: {data}")
                    time.sleep(retry_interval)
                else:
                    return {'error': f'Timeout occurred after {max_attempts} attempts'}

    # def __del__(self):
    #     """
    #     析构函数，清理资源
    #     """
    #     try:
    #         if self.device and hasattr(self, 'config') and self.config and self.config.get('avd_name'):
    #             self._stop_remote_avd(self.config.get('avd_name'))
    #     except:
    #         pass
