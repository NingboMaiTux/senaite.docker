import json

from localtest.samplefield import logger

try:
    from zope.component.hooks import getSite
except Exception:
    def getSite():
        return None


def _safe_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return ""
    return str(value)


def _get_registry():
    try:
        from zope.component import getUtility
        from plone.registry.interfaces import IRegistry
        return getUtility(IRegistry)
    except Exception:
        return None


def _get_portal(context=None):
    obj = context
    for _ in range(32):
        if obj is None:
            break
        if getattr(obj, 'portal_setup', None) is not None:
            return obj
        obj = getattr(obj, 'aq_parent', None)
    return getSite()


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
    text = _safe_text(raw).strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_extender_site_gate(context, gate_id=None, target_scope='site'):
    scope = _safe_text(target_scope).strip().lower() or 'site'
    portal = _get_portal(context)
    current_site_id = ''
    if portal is not None:
        try:
            current_site_id = _safe_text(portal.getId()).strip()
        except Exception:
            current_site_id = ''
    gates = _registry_json('localtest.samplefield.extender_gates')
    gate_meta = gates.get(gate_id) if isinstance(gates, dict) and gate_id else {}
    if not isinstance(gate_meta, dict):
        gate_meta = {}
    expected_scope = _safe_text(gate_meta.get('target_scope') or scope).strip().lower() or scope
    expected_site_id = _safe_text(gate_meta.get('site_id')).strip() or None
    allowed = True
    if expected_scope == 'site' and expected_site_id:
        allowed = current_site_id == expected_site_id
    return {
        'allowed': bool(allowed),
        'target_scope': expected_scope,
        'expected_site_id': expected_site_id,
        'current_site_id': current_site_id or None,
        'gate_id': gate_id,
    }


def import_various(context):
    if context is not None:
        marker = getattr(context, 'readDataFile', lambda *args, **kwargs: None)('localtest.samplefield.txt')
        if marker is None:
            return
    try:
        from localtest.samplefield.browser.viewlets import apply_listing_patches
        portal = context.getSite() if context is not None and hasattr(context, 'getSite') else getSite()
        apply_listing_patches(portal)
    except Exception:
        logger.exception('Failed to apply listing patches during import')


def post_install(portal_setup):
    logger.info('localtest.samplefield post-install')


def post_uninstall(portal_setup):
    logger.info('localtest.samplefield post-uninstall')
