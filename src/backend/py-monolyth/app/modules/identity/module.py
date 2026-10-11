"""Описание модуля `identity` для shared kernel (ADR-002, раздел 3.2)."""

from app.core.modules import ModuleDefinition
from app.modules.identity.api.router import router
from app.modules.identity.models import Base, outbox
from app.modules.identity.permissions import module_permissions
from app.modules.identity.public.topics import TOPICS
from app.modules.identity.settings import IdentitySettings


module = ModuleDefinition(
    name="identity",
    metadata=Base.metadata,
    router=router,
    settings=IdentitySettings(),
    permissions=module_permissions(),
    topics=TOPICS,
    outbox=outbox,
)
