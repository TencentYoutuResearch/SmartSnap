# pylint: disable=line-too-long, function-name-too-long
import os
import asyncio
from rich import print
from typing import Literal, Dict, Any
from dotenv import load_dotenv, find_dotenv
from tencentcloud.common.common_client import CommonClient
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile

load_dotenv(find_dotenv(raise_error_if_not_found=True), verbose=True)
print(f"> using TENCENTCLOUD_SECRET_ID: {os.getenv('TENCENTCLOUD_SECRET_ID')}")
print(f"> using TENCENTCLOUD_RESOURCE_GROUP_ID: {os.getenv('TENCENTCLOUD_RESOURCE_GROUP_ID')}")

para_create_os = {
    'EnvType': 'OS', 
    'ResourceGroupId': os.getenv("TENCENTCLOUD_RESOURCE_GROUP_ID"), 
    'ResourceInfo': {'Cpu': 4000, 'Memory': 8000}, 
    'DataConfigs': [{
        'MappingPath': '/tmp',
        'DataSourceType': 'CFS', 
    }],
    'ImageInfo': {
        "ImageType": "CCR",
        "ImageUrl": "{android_lab_docker_image_url}", 
        "RegistryRegion": "ap-guangzhou",
    },
    "Port": 6060, 
    'AutoStopConfig': {'AutoStop': True, 'AutoStopMinutes': 30}
}



class TioneEnvManager:
    
    def __init__(self, type: Literal["OS"]="OS", image_info: dict = None, is_debug=False):
        assert type == "OS", "Only Support OS Type"
        self.create_params = para_create_os.copy()
        self.is_debug = is_debug
        if image_info is not None:
            self.create_params['ImageInfo'] = image_info.copy()
        cred = credential.Credential(os.getenv("TENCENTCLOUD_SECRET_ID"), os.getenv("TENCENTCLOUD_SECRET_KEY"))
        httpProfile = HttpProfile()
        httpProfile.endpoint = "tione.tencentcloudapi.com"
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        if os.getenv('TENCENTCLOUD_RESOURCE_GROUP_ID') == "{tione-beijing-resource-group}":
            region = "ap-beijing"
        elif os.getenv('TENCENTCLOUD_RESOURCE_GROUP_ID') == "{tione-guangzhou-resource-group}":
            region = "ap-guangzhou"
        else:
            raise ValueError("Invalid Resource Group ID")
        self.resource_group_id = os.getenv('TENCENTCLOUD_RESOURCE_GROUP_ID')
        self.region = region
        print("resource-id", self.resource_group_id, "region", self.region)
        self.client = CommonClient("tione", "2021-11-11", cred, region, profile=clientProfile)
        self.semaphore = asyncio.Semaphore(32)


    async def describe_env(self, env_id: str = None) -> str:
        env_id = env_id or self.env_id
        loop = asyncio.get_running_loop()
        async with self.semaphore:
            res = await loop.run_in_executor(
                None,
                lambda: self.client.call_json("DescribeAgentToolInfoByEnvId", {'EnvId': env_id})
            )

        self.status = res['Response']['AgentToolEnvInfo']['Status']
        self.endpoint = res['Response']['AgentToolEnvInfo']['Endpoint']
        return self.status


    async def describe_envs(self) -> list[dict]:
        loop = asyncio.get_running_loop()
        async with self.semaphore:
            res = await loop.run_in_executor(
                None,
                lambda: self.client.call_json("DescribeAgentToolEnvs", {'Limit': 150})
            )
        
        status_mapping = {}
        none_endpoint_cnt = 0
        print(len(res["Response"]["AgentToolEnvInfos"]))
        for line in res["Response"]["AgentToolEnvInfos"]:
            status_mapping[line["Status"]] = status_mapping.get(line["Status"], 0) + 1
            if line["Endpoint"] == "":
                none_endpoint_cnt += 1
        print(f"Number of instances: {res['Response']['TotalCount']}, {none_endpoint_cnt = }, {status_mapping = }")
        return res['Response']['AgentToolEnvInfos']

    async def create_env(self):
        params = self.create_params.copy()
        
        loop = asyncio.get_running_loop()
        async with self.semaphore:
            response = await loop.run_in_executor(
                None,
                lambda: self.client.call_json("CreateAgentToolEnv", params)
            )
        
        # print(response)
        self.env_id = response['Response']['AgentToolEnvInfo']['EnvId']
        self.status = ""  # status & endpoint is empty as begin
        self.endpoint = ""
        # print(f"EnvId: {self.env_id}\nEndpoint: {self.endpoint}\nStatus: {self.status}")
        if not self.is_debug:
            while self.status in ("", "CREATED"):
                await asyncio.sleep(1)
                await self.describe_env() # Now correctly awaiting the async version
                # print(f"Status: {self.status}")
        else:
            while self.status != "CREATED":
                await asyncio.sleep(1)
                print(">>> 等待环境ready")
                await self.describe_env() # Now correctly awaiting the async version            
            
        return {
            "env_id": self.env_id,
            "endpoint": self.endpoint,
            "status": self.status
        }

    async def delete_env(self, env_id: str = None):
        env_id = env_id or self.env_id
        loop = asyncio.get_running_loop()
        num_time_not_found = 0
        while True:
            try:
                # First, try to delete the environment.
                # This might fail if it's already being deleted, but that's okay.
                print(f"Attempting to delete env: {env_id}")
                async with self.semaphore:
                    await loop.run_in_executor(
                        None,
                        lambda: self.client.call_json("DeleteAgentToolEnv", {'EnvId': env_id})
                    )
                # Wait a moment before checking the status
                await asyncio.sleep(15)
                # Check if the environment still exists.
                # If describe_env succeeds, it means the env is not deleted yet.
                status = await self.describe_env(env_id)
                print(f"Env {env_id} still exists with status: {status}. Retrying deletion...")

            except TencentCloudSDKException as e:
                # If the resource is not found, it means deletion was successful.
                if "record not found request" in str(e):
                    print(f"Env {env_id} is being deleted {num_time_not_found+1}-th time.")
                    num_time_not_found += 1
                    await asyncio.sleep(5)
                    if num_time_not_found >= 3:
                        # it has a lot of time laps here
                        # has to delete multiple times
                        print(f"Env {env_id} successfully deleted.")
                        break
                else:
                    # Handle other potential API errors during check
                    print(f"An unexpected API error occurred while checking env {env_id}: {e}. Retrying...")
                    await asyncio.sleep(5)
            except Exception as e:
                # Handle other unexpected errors
                print(f"An unexpected error occurred: {e}. Stopping deletion attempt for {env_id}.")
                break

    async def delete_all_envs(self):
        envs = await self.describe_envs()
        print(f">>> 该地域 {self.region} 全部实例 {len(envs)}")
        delete_tasks = []
        for env in envs:
            print(f"Queueing deletion for env: {env['EnvId']}, status: {env['Status']}, endpoint: {env['Endpoint']}")
            # Create a task for each deletion
            task = asyncio.create_task(self.delete_env(env['EnvId']))
            delete_tasks.append(task)
        
        # Wait for all deletion tasks to complete
        if delete_tasks:
            await asyncio.gather(*delete_tasks)

    async def delete_all_envs_by_resource(self):
        envs = await self.describe_envs()
        print(f">>> 该地域 {self.region} 全部实例 {len(envs)}")
        envs = [env for env in envs if env['ResourceGroupId'] == self.resource_group_id]
        print(f">>> 该地域资源组 {self.resource_group_id} 全部实例 {len(envs)}")
        delete_tasks = []
        for env in envs:
            print(f"Queueing deletion for env: {env['EnvId']}, status: {env['Status']}, endpoint: {env['Endpoint']}")
            # Create a task for each deletion
            task = asyncio.create_task(self.delete_env(env['EnvId']))
            delete_tasks.append(task)
        
        # Wait for all deletion tasks to complete
        if delete_tasks:
            await asyncio.gather(*delete_tasks)


async def test_flow(task_id: int, semaphore: asyncio.Semaphore) -> Dict[str, Any]:
    """单个测试流程"""
    async with semaphore:
        print(f"[Task-{task_id}] 开始测试")
        manager = TioneEnvManager(type='OS', is_debug=True)
        
        try:
            # 1. 查询环境列表
            print(f"[Task-{task_id}] 查询环境中...")
            envs = await manager.describe_envs()
            print(f"[Task-{task_id}] 当前环境数: {len(envs) if isinstance(envs, list) else 'N/A'}")
            
            # 2. 创建环境
            print(f"[Task-{task_id}] 创建环境中...")
            env = await manager.create_env()
            env_id = env["env_id"]
            print(f"[Task-{task_id}] 环境创建成功: {env_id}")
            
            # 3. 等待5秒
            print(f"[Task-{task_id}] 等待600秒...")  # ✅ 修复：task-id -> task_id
            await asyncio.sleep(600)
            
            # 4. 删除环境
            print(f"[Task-{task_id}] 删除环境: {env_id}")
            await manager.delete_env(env_id)
            print(f"[Task-{task_id}] 环境删除成功")
            
            return {"task_id": task_id, "status": "success", "env_id": env_id}
            
        except Exception as e:
            print(f"[Task-{task_id}] 测试失败: {str(e)}")
            return {"task_id": task_id, "status": "failed", "error": str(e)}




async def run_concurrent_test(concurrency: int = 32):
    """并发测试主函数"""
    semaphore = asyncio.Semaphore(concurrency)  # 控制并发数
    
    # 创建32个并发任务
    tasks = [
        test_flow(task_id=i, semaphore=semaphore)
        for i in range(1, concurrency + 1)
    ]
    
    # 等待所有任务完成
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 统计结果
    success_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "success")
    failed_count = concurrency - success_count
    
    print("\n" + "="*50)
    print(f"测试完成 - 总计: {concurrency}, 成功: {success_count}, 失败: {failed_count}")
    print("="*50)
    
    return results

    
if __name__ == '__main__':
    print()
