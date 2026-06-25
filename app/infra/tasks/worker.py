"""arq Worker 配置。独立进程启动：arq app.infra.tasks.worker.WorkerSettings"""

from arq.connections import RedisSettings
from app.infra.cache.manager import get_redis_settings

_host, _port = get_redis_settings()


class WorkerSettings:
    redis_settings = RedisSettings(host=_host, port=_port)
    functions = [
        "app.infra.tasks.jobs.build_rag_job",
        "app.infra.tasks.jobs.eval_run_job",
        "app.infra.tasks.jobs.batch_analyze_job",
    ]
    max_jobs = 10
    job_timeout = 600        # 单个任务最长 10 分钟
    keep_result = 3600       # 结果保留 1 小时
    allow_abort_jobs = True
