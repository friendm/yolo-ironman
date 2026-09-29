from .models import AuditLog


def record(actor, action, obj=None, *, entity=None, **details):
    """Write one audit row. Document views and downloads always go through here."""
    user = actor if getattr(actor, "is_authenticated", False) else None
    return AuditLog.objects.create(
        actor_user=user,
        action=action,
        entity=entity or (obj._meta.model_name if obj is not None else ""),
        entity_id=getattr(obj, "pk", None),
        details={k: (str(v) if v is not None else None) for k, v in details.items()},
    )
