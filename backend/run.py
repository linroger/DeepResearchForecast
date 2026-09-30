"""
MiroFish Backend 启动入口
"""

import os
import sys

# 解决 Windows 控制台中文乱码问题：在所有导入之前设置 UTF-8 编码
if sys.platform == 'win32':
    # 设置环境变量确保 Python 使用 UTF-8
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # 重新配置标准输出流为 UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config


def main():
    """主函数"""
    # 验证配置
    errors = Config.validate(include_audit=False)
    if errors:
        print("配置错误:")
        for err in errors:
            print(f"  - {err}")
        print("\n请检查 .env 文件中的配置")
        sys.exit(1)
    # INFRA-14: the config audit never stops the server; its errors refuse pipeline runs
    # while CONFIG_STRICT_VALIDATION is on (preflight / PipelineOrchestrator.start).
    for issue in Config.config_issues():
        print(f"WARN config {issue.level}: {issue.message}")

    # 创建应用
    app = create_app()

    # i8：MON-1 判定监测的进程内调度（RESOLUTION_MONITOR_AUTORUN_HOURS>0 才启动；默认 0=关）。
    # 只在生产入口挂——create_app() 的测试消费者绝不自启后台网络轮询。
    from app.services.resolution_autorun import start as start_resolution_autorun
    start_resolution_autorun()
    
    # 获取运行配置
    # 默认仅绑定环回（EXECPLAN2 F-13-0）：服务无鉴权时不应暴露在所有网卡上。
    # 需要局域网访问时显式设 FLASK_HOST=0.0.0.0，并务必同时配置 APP_API_TOKEN。
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', 5001))
    debug = Config.DEBUG
    if host not in ('127.0.0.1', 'localhost', '::1') and not Config.APP_API_TOKEN:
        print(
            f"⚠️  绑定到 {host} 但未设置 APP_API_TOKEN —— 所有变更类接口将对网络开放且无鉴权。\n"
            f"   建议：设置 APP_API_TOKEN 后再以非环回地址启动。"
        )
    
    # 启动服务
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    main()

