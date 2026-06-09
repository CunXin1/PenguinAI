from fastapi import APIRouter

from . import actions, database, datasources, health, logs, models, tasks, users

router = APIRouter()

router.include_router(health.router, prefix="/health", tags=["admin-health"])
router.include_router(database.router, prefix="/db", tags=["admin-db"])
router.include_router(tasks.router, prefix="/tasks", tags=["admin-tasks"])
router.include_router(datasources.router, prefix="/datasources", tags=["admin-datasources"])
router.include_router(models.router, prefix="/models", tags=["admin-models"])
router.include_router(users.router, prefix="/users", tags=["admin-users"])
router.include_router(actions.router, prefix="/actions", tags=["admin-actions"])
router.include_router(logs.router, tags=["admin-logs"])
