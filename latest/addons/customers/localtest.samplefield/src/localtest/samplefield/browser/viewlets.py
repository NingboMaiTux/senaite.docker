import json


def _get_registry():
    try:
        from zope.component import getUtility
        from plone.registry.interfaces import IRegistry
        return getUtility(IRegistry)
    except Exception:
        return None


def _registry_json(key):
    reg = _get_registry()
    if reg is None:
        return {}
    raw = ''
    try:
        raw = reg.get(key, '')
    except Exception:
        try:
            raw = reg.records[key].value
        except Exception:
            raw = ''
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8')
        except Exception:
            raw = ''
    raw = str(raw or '').strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def apply_listing_patches(portal=None):
    patches = _registry_json('localtest.samplefield.listing_patches')
    changed = False
    for view_class, meta in patches.items():
        if not isinstance(view_class, str) or '.' not in view_class:
            continue
        try:
            mod_name, cls_name = view_class.rsplit('.', 1)
            mod = __import__(mod_name, fromlist=[cls_name])
            view_cls = getattr(mod, cls_name)
        except Exception:
            continue
        current = getattr(view_cls, 'columns', None) or {}
        if not isinstance(current, dict):
            current = {}
        patched = dict(current)
        columns = meta.get('columns') if isinstance(meta, dict) else []
        for item in columns if isinstance(columns, list) else []:
            if not isinstance(item, dict):
                continue
            column_id = str(item.get('column_id') or '').strip()
            if not column_id:
                continue
            entry = patched.get(column_id)
            if not isinstance(entry, dict):
                entry = {}
            entry.setdefault('title', item.get('title') or column_id)
            entry['toggle'] = bool(item.get('toggle')) if item.get('toggle') is not None else True
            patched[column_id] = entry
        view_cls.columns = patched
        changed = True
    return changed
