# pylint: disable=line-too-long, function-name-too-long
#!/usr/bin/env python3
"""
Docker 管理器工厂 - 简化 Docker 管理器的创建和配置

这个模块提供了一个工厂函数来创建不同类型的 Docker 管理器，
使用户能够轻松地在不同的管理器之间切换。
"""

import os
import sys
from typing import Dict, Any, Optional, Literal

# 处理相对导入
try:
    from .mobile_session import DockerManagerInterface, AdvancedDockerManager, TioneDockerManager, LegacyDockerManager
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from svagent.mobile_session import DockerManagerInterface, AdvancedDockerManager, TioneDockerManager, LegacyDockerManager


class DockerManagerFactory:
    """Docker 管理器工厂类"""
    
    @staticmethod
    def create_manager(
        manager_type: Literal["advanced", "tione", "legacy"] = "advanced",
        **kwargs
    ) -> DockerManagerInterface:
        """
        创建 Docker 管理器实例
        
        Args:
            manager_type: 管理器类型
                - "advanced": 使用高级调度器 (推荐)
                - "tione": 直接使用 Tione 服务
                - "legacy": 传统调度器 (已废弃)
            **kwargs: 管理器特定的参数
            
        Returns:
            DockerManagerInterface: Docker 管理器实例
        """
        
        if manager_type == "advanced":
            return DockerManagerFactory._create_advanced_manager(**kwargs)
        elif manager_type == "tione":
            return DockerManagerFactory._create_tione_manager(**kwargs)
        elif manager_type == "legacy":
            return DockerManagerFactory._create_legacy_manager(**kwargs)
        else:
            raise ValueError(f"不支持的管理器类型: {manager_type}")
    
    @staticmethod
    def _create_advanced_manager(
        scheduler_url: str = "http://localhost:8080",
        client_id: Optional[str] = None,
        **kwargs
    ) -> AdvancedDockerManager:
        """创建高级 Docker 管理器"""
        return AdvancedDockerManager(
            scheduler_url=scheduler_url,
            client_id=client_id
        )
    
    @staticmethod
    def _create_tione_manager(
        env_type: str = "OS",
        image_info: Optional[Dict] = None,
        **kwargs
    ) -> TioneDockerManager:
        """创建 Tione Docker 管理器"""
        return TioneDockerManager(
            env_type=env_type,
            image_info=image_info
        )
    
    @staticmethod
    def _create_legacy_manager(
        scheduler_url: str,
        **kwargs
    ) -> LegacyDockerManager:
        """创建传统 Docker 管理器"""
        print("警告: 正在创建已废弃的 LegacyDockerManager")
        return LegacyDockerManager(scheduler_url=scheduler_url)
    
    @staticmethod
    def create_from_config(config: Dict[str, Any]) -> DockerManagerInterface:
        """
        从配置字典创建 Docker 管理器
        
        Args:
            config: 配置字典，应包含以下键：
                - docker_manager_type: 管理器类型
                - docker_manager_config: 管理器特定配置
                
        Example:
            config = {
                "docker_manager_type": "advanced",
                "docker_manager_config": {
                    "scheduler_url": "http://scheduler:8080",
                    "client_id": "my_client"
                }
            }
        """
        manager_type = config.get("docker_manager_type", "advanced")
        manager_config = config.get("docker_manager_config", {})
        
        return DockerManagerFactory.create_manager(
            manager_type=manager_type,
            **manager_config
        )
    
    @staticmethod
    def create_from_env() -> DockerManagerInterface:
        """
        从环境变量创建 Docker 管理器
        
        环境变量：
            - DOCKER_MANAGER_TYPE: 管理器类型 (advanced|tione|legacy)
            - ADVANCED_SCHEDULER_URL: 高级调度器 URL
            - DOCKER_CLIENT_ID: 客户端 ID
            - LEGACY_SCHEDULER_URL: 传统调度器 URL
        """
        manager_type = os.getenv("DOCKER_MANAGER_TYPE", "advanced")
        
        if manager_type == "advanced":
            return AdvancedDockerManager(
                scheduler_url=os.getenv("ADVANCED_SCHEDULER_URL", "http://localhost:8080"),
                client_id=os.getenv("DOCKER_CLIENT_ID")
            )
        elif manager_type == "tione":
            return TioneDockerManager()
        elif manager_type == "legacy":
            legacy_url = os.getenv("LEGACY_SCHEDULER_URL")
            if not legacy_url:
                raise ValueError("使用 legacy 管理器时必须设置 LEGACY_SCHEDULER_URL 环境变量")
            return LegacyDockerManager(scheduler_url=legacy_url)
        else:
            raise ValueError(f"不支持的管理器类型: {manager_type}")


def get_recommended_manager(
    use_case: Literal["development", "testing", "production", "ci_cd"] = "development"
) -> Dict[str, Any]:
    """
    根据使用场景推荐管理器配置
    
    Args:
        use_case: 使用场景
        
    Returns:
        推荐的配置字典
    """
    
    recommendations = {
        "development": {
            "manager_type": "tione",
            "config": {},
            "reason": "开发阶段使用 Tione 直连，简单快速"
        },
        "testing": {
            "manager_type": "advanced",
            "config": {
                "scheduler_url": "http://localhost:8080",
                "client_id": "test_client"
            },
            "reason": "测试阶段使用高级调度器，支持并发测试"
        },
        "production": {
            "manager_type": "advanced",
            "config": {
                "scheduler_url": "http://scheduler.production:8080",
                "client_id": None  # 自动生成
            },
            "reason": "生产环境使用高级调度器，稳定可靠"
        },
        "ci_cd": {
            "manager_type": "advanced",
            "config": {
                "scheduler_url": "http://ci-scheduler:8080",
                "client_id": "ci_pipeline"
            },
            "reason": "CI/CD 使用高级调度器，支持并行构建"
        }
    }
    
    return recommendations.get(use_case, recommendations["development"])


# 便捷函数
def create_advanced_manager(scheduler_url: str = "http://localhost:8080", 
                          client_id: Optional[str] = None) -> AdvancedDockerManager:
    """便捷函数：创建高级 Docker 管理器"""
    return DockerManagerFactory.create_manager("advanced", 
                                              scheduler_url=scheduler_url, 
                                              client_id=client_id)


def create_tione_manager(env_type: str = "OS", 
                        image_info: Optional[Dict] = None) -> TioneDockerManager:
    """便捷函数：创建 Tione Docker 管理器"""
    return DockerManagerFactory.create_manager("tione", 
                                              env_type=env_type, 
                                              image_info=image_info)


if __name__ == "__main__":
    # 示例用法
    print("=== Docker 管理器工厂示例 ===")
    
    # 方式1: 直接创建
    print("\n1. 直接创建高级管理器:")
    advanced_mgr = create_advanced_manager("http://localhost:8080")
    print(f"   类型: {type(advanced_mgr).__name__}")
    
    # 方式2: 从配置创建
    print("\n2. 从配置创建:")
    config = {
        "docker_manager_type": "advanced",
        "docker_manager_config": {
            "scheduler_url": "http://scheduler:8080",
            "client_id": "config_client"
        }
    }
    config_mgr = DockerManagerFactory.create_from_config(config)
    print(f"   类型: {type(config_mgr).__name__}")
    
    # 方式3: 获取推荐配置
    print("\n3. 获取推荐配置:")
    for use_case in ["development", "testing", "production", "ci_cd"]:
        recommendation = get_recommended_manager(use_case)
        print(f"   {use_case}: {recommendation['manager_type']} - {recommendation['reason']}")