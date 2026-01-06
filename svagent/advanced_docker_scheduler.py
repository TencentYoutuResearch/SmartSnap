# pylint: disable=line-too-long, function-name-too-long
import os
import sys
import asyncio
import time
import json
import logging
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from enum import Enum
from concurrent.futures import TimeoutError
import httpx
from aiohttp import web



# 添加项目路径以支持直接运行
if __name__ == "__main__":
    # This path adjustment is for direct execution of the script.
    # It might need to be adapted depending on the project structure.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    # Assuming docker_client_tione is in the same package `svagent`
    from .docker_client_tione import TioneEnvManager
except (ImportError, ModuleNotFoundError):
    # Fallback for direct script execution
    from svagent.docker_client_tione import TioneEnvManager

# --- Logging Setup ---
# Use a logger that can be shared across modules
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('docker_scheduler.log'),
            logging.StreamHandler()
        ]
    )

# --- Core Scheduler Classes (migrated from advanced_docker_scheduler.py) ---

class InstanceStatus(Enum):
    """实例状态枚举"""
    CREATING = "creating"
    TESTING = "testing"
    READY = "ready"
    ALLOCATED = "allocated"
    DESTROYING = "destroying"
    FAILED = "failed"

@dataclass
class DockerInstance:
    """Docker实例数据类"""
    instance_id: str
    env_id: str
    endpoint: str
    status: InstanceStatus
    created_at: datetime
    allocated_at: Optional[datetime] = None
    client_id: Optional[str] = None
    last_health_check: Optional[datetime] = None
    error_message: str = ""
    
    def to_dict(self) -> dict:
        """转换为字典"""
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, InstanceStatus):
                data[key] = value.value
        return data

class DockerScheduler:
    """高级Docker调度器"""
    
    def __init__(self, 
                 pool_size: int = 3,
                 max_pool_size: int = 10,
                 api_test_timeout: int = 900,
                 health_check_interval: int = 1200,
                 resource_config: dict = None):
        self.pool_size = pool_size
        self.max_pool_size = max_pool_size
        self.api_test_timeout = api_test_timeout
        self.health_check_interval = health_check_interval
        self.resource_config = resource_config or {'Cpu': 4000, 'Memory': 8000}
        
        self.instances: Dict[str, DockerInstance] = {}
        self.ready_queue: Optional[asyncio.Queue] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        
        self.running = False
        self.stats = {
            'total_created': 0,
            'total_allocated': 0,
            'total_destroyed': 0,
            'total_failed': 0,
            'start_time': datetime.now()
        }
        
    async def start(self):
        """启动调度器后台任务"""
        if self.running:
            logger.info("Scheduler is already running.")
            return
            
        logger.info(f"🚀 启动Docker调度器 - 目标池大小: {self.pool_size}")
        self.running = True
        self.loop = asyncio.get_running_loop()
        
        # Initialize the queue in the same event loop
        self.ready_queue = asyncio.Queue()

        # Start background tasks
        self.background_tasks = [
            asyncio.create_task(self._pool_manager()),
            asyncio.create_task(self._health_checker()),
            asyncio.create_task(self._stats_reporter())
        ]

    async def shutdown(self):
        """关闭调度器并清理资源"""
        logger.info("🛑 开始关闭调度器...")
        self.running = False

        # Cancel background tasks
        for task in self.background_tasks:
            task.cancel()
        await asyncio.gather(*self.background_tasks, return_exceptions=True)
        
        # Destroy all existing instances
        destroy_tasks = [
            self._destroy_instance(instance_id) 
            for instance_id in list(self.instances.keys())
        ]
        if destroy_tasks:
            await asyncio.gather(*destroy_tasks, return_exceptions=True)
        
        logger.info("✅ 调度器已关闭")

    async def _create_instance(self) -> Optional[DockerInstance]:
        instance_id = f"inst_{int(time.time())}_{os.urandom(4).hex()}"
        instance = DockerInstance(
            instance_id=instance_id, env_id="", endpoint="",
            status=InstanceStatus.CREATING, created_at=datetime.now()
        )
        self.instances[instance_id] = instance
        
        try:
            logger.info(f"🔨 开始创建实例: {instance_id}")
            manager = TioneEnvManager(type='OS')
            manager.create_params['ResourceInfo'] = self.resource_config.copy()
            
            start_time = time.time()
            env_result = await manager.create_env()
            creation_time = time.time() - start_time
            
            env_id = env_result.get('env_id')
            endpoint = env_result.get('endpoint')
            
            if not env_id or not endpoint:
                raise Exception(f"创建失败，返回信息不完整: {env_result}")

            logger.info(f"🏗️ 实例 {instance_id} 环境创建完成，耗时: {creation_time:.1f}s")
            
            instance.env_id = env_id
            instance.endpoint = endpoint
            instance.status = InstanceStatus.TESTING
            self.stats['total_created'] += 1
            
            if await self._test_instance_api(instance):
                instance.status = InstanceStatus.READY
                instance.last_health_check = datetime.now()
                await self.ready_queue.put(instance_id)
                total_time = time.time() - start_time
                logger.info(f"✅ 实例 {instance_id} 就绪，总耗时: {total_time:.1f}s")
                return instance
            else:
                raise Exception("API测试失败")
                
        except Exception as e:
            logger.error(f"❌ 创建实例 {instance_id} 失败: {e}")
            instance.status = InstanceStatus.FAILED
            instance.error_message = str(e)
            self.stats['total_failed'] += 1
            await self._destroy_instance(instance_id)
            return None
    
    async def _test_instance_api(self, instance: DockerInstance) -> bool:
        logger.info(f"🧪 测试实例 {instance.instance_id} API at {instance.endpoint}")
        url = f"http://{instance.endpoint}/start"
        payload = {"avd_name": "Pixel_7_Pro_API_33"}

        loop = asyncio.get_running_loop()
        async def make_request():
            # requests is blocking, run it in an executor
            return await loop.run_in_executor(
                None, 
                lambda: requests.post(url, json=payload, timeout=120)
            )

        start_time = time.time()
        while time.time() - start_time < self.api_test_timeout:
            try:
                response = await make_request()
                if response.status_code in [200, 201, 202]:
                    logger.info(f"✅ 实例 {instance.instance_id} API测试成功")
                    return True
            except requests.exceptions.RequestException:
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"API test unexpected error for {instance.instance_id}: {e}")
                break # Exit on unexpected error
        
        logger.error(f"❌ 实例 {instance.instance_id} API测试超时或失败")
        return False
    
    async def _destroy_instance(self, instance_id: str):
        instance = self.instances.get(instance_id)
        if not instance:
            return
        
        instance.status = InstanceStatus.DESTROYING
        logger.info(f"🗑️ 销毁实例 {instance_id} (EnvId: {instance.env_id})")
        
        try:
            if instance.env_id:
                manager = TioneEnvManager(type='OS')
                await manager.delete_env(instance.env_id)
                logger.info(f"✅ 实例 {instance_id} 云端环境销毁成功")
        except Exception as e:
            logger.error(f"❌ 销毁实例 {instance_id} 云端环境失败: {e}")
        finally:
            if instance_id in self.instances:
                del self.instances[instance_id]
                self.stats['total_destroyed'] += 1
                logger.info(f"🗑️ 实例 {instance_id} 已从本地移除")
    
    async def _pool_manager(self):
        """池管理器 - 初始化并维护目标池大小"""
        logger.info(f"📦 池管理器启动 - 目标池大小: {self.pool_size}")
        
        is_initial_startup = True
        
        while self.running:
            try:
                # 统计当前状态
                ready_count = self.ready_queue.qsize()
                creating_count = sum(1 for inst in self.instances.values() if inst.status == InstanceStatus.CREATING)
                testing_count = sum(1 for inst in self.instances.values() if inst.status == InstanceStatus.TESTING)
                allocated_count = sum(1 for inst in self.instances.values() if inst.status == InstanceStatus.ALLOCATED)
                
                total_active = ready_count + creating_count + testing_count
                total_instances = len(self.instances)
                
                # 根据启动阶段选择日志级别
                if is_initial_startup and total_instances == 0:
                    logger.info(f"🚀 开始初始化实例池，并行创建 {self.pool_size} 个实例...")
                elif is_initial_startup:
                    logger.info(f"🔍 初始化进行中 - 就绪:{ready_count} 创建中:{creating_count} 测试中:{testing_count} 总计:{total_instances}")
                else:
                    logger.debug(f"🔍 池状态检查 - 就绪:{ready_count} 创建中:{creating_count} 测试中:{testing_count} 已分配:{allocated_count} 总实例:{total_instances}")

                # 如果池中实例不足，创建新实例
                needed = self.pool_size - total_active
                
                # 额外的安全检查：不能超过最大池大小
                can_create = self.max_pool_size - total_instances
                
                # 新增：限制并发创建数量
                concurrent_creation_limit = 128
                ongoing_creations = creating_count + testing_count
                creation_slots_available = max(0, concurrent_creation_limit - ongoing_creations)
                
                actual_needed = min(needed, can_create, creation_slots_available)
                print(f"正在创建/测试的实例: {ongoing_creations}, 同时创建信号量: {concurrent_creation_limit}, 需要创建的数量: {needed}, 本次可同时创建的数量: {can_create}")
                if actual_needed > 0:
                    if is_initial_startup:
                        logger.info(f"📈 初始化创建 {actual_needed} 个新实例")
                    else:
                        logger.info(f"📈 池中实例不足 - 目标:{self.pool_size} 当前活跃:{total_active} 需要创建:{actual_needed} 个新实例")
                    
                    tasks = [self._create_instance() for _ in range(actual_needed)]
                    await asyncio.gather(*tasks)

                elif total_instances >= self.max_pool_size:
                    if not is_initial_startup:
                        logger.warning(f"⚠️ 已达到最大池大小限制 {self.max_pool_size}，不再创建新实例")
                elif ongoing_creations >= concurrent_creation_limit:
                    logger.info(f"⏳ 并发创建达到上限({concurrent_creation_limit})，等待现有实例完成...")

                # 检查初始化是否完成
                if is_initial_startup and ready_count >= self.pool_size:
                    is_initial_startup = False
                    logger.info(f"✅ 初始化阶段完成 - 就绪实例:{ready_count} 总实例:{total_instances}")
                
                # 调整检查间隔
                sleep_time = 3 if is_initial_startup else 10
                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                logger.info("池管理器被取消")
                break
            except Exception as e:
                logger.error(f"池管理器错误: {e}", exc_info=True)
                await asyncio.sleep(10)
    

    async def _health_checker(self):
        """健康检查器"""
        while self.running:
            try:
                await asyncio.sleep(self.health_check_interval)
                current_time = datetime.now()
                for instance in list(self.instances.values()):
                    if instance.status == InstanceStatus.READY:
                        if (instance.last_health_check is None or 
                            current_time - instance.last_health_check > timedelta(seconds=self.health_check_interval)):
                            asyncio.create_task(self._check_instance_health(instance))
            except asyncio.CancelledError:
                logger.info("健康检查器被取消")
                break
            except Exception as e:
                logger.error(f"健康检查器错误: {e}", exc_info=True)
                await asyncio.sleep(10)


    async def _check_instance_health(self, instance: DockerInstance):
        """检查单个实例健康状态"""
        logger.debug(f"🩺 健康检查实例: {instance.instance_id}")
        try:
            url = f"http://{instance.endpoint}/start"
            payload = {"avd_name": "Pixel_7_Pro_API_33"}

            # 使用httpx来创建
            # async with httpx.AsyncClient(timeout=120.0) as client:  # 明确指定秒
            #     response = await client.post(
            #         f"http://{instance.endpoint}/start",
            #         json={"avd_name": "Pixel_7_Pro_API_33"}
            #     )
            #     response.raise_for_status()  # 自动处理4xx/5xx

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, json=payload, timeout=120)
            )
            if response.status_code in [200, 201, 202]:
                instance.last_health_check = datetime.now()
                logger.debug(f"✅ 实例 {instance.instance_id} 健康检查通过")
            else:
                logger.warning(f"⚠️ 实例 {instance.instance_id} 健康检查失败，状态码: {response.status_code}")
                await self._handle_unhealthy_instance(instance)
                
        except Exception as e:
            logger.warning(f"⚠️ 实例 {instance.instance_id} 健康检查异常: {e}")
            await self._handle_unhealthy_instance(instance)

    async def _handle_unhealthy_instance(self, instance: DockerInstance):
        """处理不健康的实例"""
        logger.warning(f"🔄 处理不健康实例: {instance.instance_id}")
        
        # 从就绪队列中移除 (如果存在)
        # 这是一个尽力而为的操作，因为asyncio.Queue没有直接的remove方法
        temp_queue = asyncio.Queue()
        removed = False
        while not self.ready_queue.empty():
            item = await self.ready_queue.get()
            if item == instance.instance_id and not removed:
                removed = True
                logger.info(f"🔪 从就绪队列中移除不健康实例: {instance.instance_id}")
            else:
                await temp_queue.put(item)
        
        # 将其他实例放回原队列
        while not temp_queue.empty():
            await self.ready_queue.put(await temp_queue.get())
            
        # 销毁实例
        await self._destroy_instance(instance.instance_id)
    
    async def _stats_reporter(self):
        while self.running:
            try:
                await asyncio.sleep(60)
                self._log_stats()
            except asyncio.CancelledError:
                logger.info("统计报告器被取消")
                break
            except Exception as e:
                logger.error(f"统计报告器错误: {e}", exc_info=True)
    
    def _log_stats(self):
        status_counts = {status.value: 0 for status in InstanceStatus}
        for instance in self.instances.values():
            status_counts[instance.status.value] += 1
        
        uptime = datetime.now() - self.stats['start_time']

        logger.info(f"📊 调度器状态 - 就绪:{self.ready_queue.qsize()} 已分配:{status_counts['allocated']} "
                    f"创建中:{status_counts['creating']} 测试中:{status_counts['testing']} "
                    f"失败:{status_counts['failed']} 总实例:{len(self.instances)}")
        logger.info(f"📈 统计信息 - 总创建:{self.stats['total_created']} 总分配:{self.stats['total_allocated']} "
                    f"总销毁:{self.stats['total_destroyed']} 运行时间:{uptime}")
    
    # --- Client API Methods ---

    async def allocate_instance(self, client_id: str) -> Optional[Dict]:
        logger.info(f"🎯 客户端 {client_id} 请求分配实例")

        current_loop = asyncio.get_running_loop()
        timeout = 3

        try:
            # If the current coroutine is running on a different event loop
            # from the one the scheduler started in (e.g., aiohttp worker),
            # we must use thread-safe methods to interact with the queue.
            if self.loop and current_loop is not self.loop:
                future = asyncio.run_coroutine_threadsafe(self.ready_queue.get(), self.loop)
                # future.result() will raise TimeoutError from concurrent.futures
                instance_id = future.result(timeout=timeout)
            else:
                # Running in the same event loop, we can await directly.
                # asyncio.wait_for will raise asyncio.TimeoutError.
                instance_id = await asyncio.wait_for(self.ready_queue.get(), timeout=timeout)
            
            instance = self.instances.get(instance_id)
            if not instance or instance.status != InstanceStatus.READY:
                logger.warning(f"Dequeued instance {instance_id} not ready, requeueing.")
                # Use thread-safe put if necessary
                if self.loop and current_loop is not self.loop:
                    asyncio.run_coroutine_threadsafe(self.ready_queue.put(instance_id), self.loop)
                else:
                    await self.ready_queue.put(instance_id)
                return None

            instance.status = InstanceStatus.ALLOCATED
            instance.allocated_at = datetime.now()
            instance.client_id = client_id
            self.stats['total_allocated'] += 1
            
            result = instance.to_dict()
            logger.info(f"✅ 为客户端 {client_id} 分配实例 {instance_id}")
            return result
            
        except (asyncio.TimeoutError, TimeoutError): # Handle both timeout types
            logger.warning(f"⏰ 客户端 {client_id} 分配实例超时")
            return None
        
        except Exception as e:
            logger.error(f"❌ 分配实例给客户端 {client_id} 时出错: {e}", exc_info=True)
            return None
    
    async def release_instance(self, instance_id: str, client_id: str) -> bool:
        logger.info(f"🔄 客户端 {client_id} 释放实例 {instance_id}")
        instance = self.instances.get(instance_id)
        
        if not instance:
            logger.warning(f"⚠️ 实例 {instance_id} 不存在")
            return False
        
        if instance.client_id != client_id:
            logger.warning(f"⚠️ 客户端 {client_id} 无权释放实例 {instance_id}")
            return False
        
        # Destroy the instance and let the pool manager create a new one
        await self._destroy_instance(instance_id)
        return True
    
    async def get_status_async(self) -> Dict:
        """获取调度器状态 (异步)"""
        status_counts = {status.value: 0 for status in InstanceStatus}
        for instance in self.instances.values():
            status_counts[instance.status.value] += 1

        return {
            'running': self.running,
            'pool_size': self.pool_size,
            'max_pool_size': self.max_pool_size,
            'ready_count': self.ready_queue.qsize(),
            'allocated_count': status_counts['allocated'],
            'creating_count': status_counts['creating'],
            'testing_count': status_counts['testing'],
            'total_instances': len(self.instances),
            'stats': self.stats,
            'uptime': (datetime.now() - self.stats['start_time']).total_seconds()
        }
    
    async def get_instances_async(self) -> List[Dict]:
        """获取所有实例信息 (异步)"""
        return [inst.to_dict() for inst in self.instances.values()]

# --- aiohttp App Handlers ---

async def get_status(request: web.Request):
    """获取调度器状态"""
    scheduler = request.app['scheduler']
    status = await scheduler.get_status_async()
    return web.json_response({'success': True, 'data': status})

async def get_instances(request: web.Request):
    """获取所有实例信息"""
    scheduler = request.app['scheduler']
    instances = await scheduler.get_instances_async()
    return web.json_response({'success': True, 'data': instances})

async def allocate_instance_handler(request: web.Request):
    """为客户端分配实例"""
    scheduler = request.app['scheduler']
    data = await request.json()
    client_id = data.get('client_id', 'unknown')
    
    result = await scheduler.allocate_instance(client_id)
    
    if result:
        return web.json_response({'success': True, 'data': result})
    else:
        return web.json_response(
            {'success': False, 'error': 'No available instances, please try again later.'},
            status=503
        )

async def release_instance_handler(request: web.Request):
    """客户端释放实例"""
    scheduler = request.app['scheduler']
    data = await request.json()
    instance_id = data.get('instance_id')
    client_id = data.get('client_id')

    if not instance_id or not client_id:
        return web.json_response(
            {'success': False, 'error': 'instance_id and client_id are required'},
            status=400
        )

    success = await scheduler.release_instance(instance_id, client_id)
    
    if success:
        return web.json_response({'success': True})
    else:
        return web.json_response(
            {'success': False, 'error': 'Failed to release instance.'},
            status=400
        )

async def on_startup(app: web.Application):
    """aiohttp startup handler"""
    scheduler = app['scheduler']
    # The scheduler's background tasks are started here, within the
    # event loop that aiohttp will use for handling requests.
    asyncio.create_task(scheduler.start())
    logger.info("🚀 Scheduler background tasks started.")

async def on_shutdown(app: web.Application):
    """aiohttp shutdown handler"""
    scheduler = app['scheduler']
    await scheduler.shutdown()
    logger.info("✅ Scheduler has been shut down.")

def create_app(scheduler: DockerScheduler) -> web.Application:
    """创建并配置aiohttp应用"""
    app = web.Application()
    app['scheduler'] = scheduler
    
    app.router.add_get('/status', get_status)
    app.router.add_get('/instances', get_instances)
    app.router.add_post('/allocate', allocate_instance_handler)
    app.router.add_post('/release', release_instance_handler)
    
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    return app

# ==================== 主程序 ====================

def main():
    """主程序"""
    import argparse
    
    parser = argparse.ArgumentParser(description='高级Docker调度器 (aiohttp版)')
    parser.add_argument('--pool-size', type=int, default=64, help='目标池大小')
    parser.add_argument('--max-pool-size', type=int, default=96, help='最大池大小')
    parser.add_argument('--api-timeout', type=int, default=900, help='API测试超时时间(秒)')
    parser.add_argument('--health-interval', type=int, default=1200, help='健康检查间隔(秒)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='HTTP API Host')
    parser.add_argument('--port', type=int, default=8080, help='HTTP API端口')
    parser.add_argument('--cpu', type=int, default=6000, help='CPU配置')
    parser.add_argument('--memory', type=int, default=12000, help='内存配置')
    args = parser.parse_args()

    # 1. 创建调度器实例
    scheduler = DockerScheduler(
        pool_size=args.pool_size,
        max_pool_size=args.max_pool_size,
        api_test_timeout=args.api_timeout,
        health_check_interval=args.health_interval,
        resource_config={'Cpu': args.cpu, 'Memory': args.memory}
    )

    # 2. 创建aiohttp应用
    app = create_app(scheduler)

    # 3. 运行应用
    # web.run_app handles graceful shutdown on Ctrl+C
    logger.info(f"🌐 aiohttp服务器将在 http://{args.host}:{args.port} 上运行")
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
