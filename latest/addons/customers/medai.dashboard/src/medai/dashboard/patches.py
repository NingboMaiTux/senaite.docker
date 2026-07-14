# -*- coding: utf-8 -*-
"""Monkey-patches for DashboardView to support Analyst role enhancements.

Applied when medai.dashboard is imported (see __init__.py), but every
patched method checks whether the add-on profile is installed in the
*current* Plone site via portal_quickinstaller.  This ensures site-level
isolation -- sites without the profile are completely unaffected.
"""

from bika.lims import api
from bika.lims.api import search
from senaite.core.browser.dashboard.dashboard import (
    DashboardView,
    SECTION_HANDLERS,
)
from senaite.core.catalog import ANALYSIS_CATALOG
from senaite.core.permissions import TransitionVerify
from senaite.core.permissions import ViewResults


PROFILE_ID = "medai.dashboard"


def _is_installed(self):
    """Return True if the medai.dashboard profile is installed
    in the *current* Plone site (self.context is the portal root).
    """
    try:
        from Products.CMFPlone.utils import getToolByName
        qi = getToolByName(self.context, "portal_quickinstaller")
        return qi.isProductInstalled(PROFILE_ID)
    except Exception:
        return False


# ===========================================================
# 1. get_status_cards -- hide Status section for Analyst
# ===========================================================

_original_get_status_cards = DashboardView.get_status_cards


def _patched_get_status_cards(self):
    if not _is_installed(self):
        return _original_get_status_cards(self)

    user = api.get_current_user()
    if user and "Analyst" in user.getRoles():
        return []
    return _original_get_status_cards(self)


# ===========================================================
# 2. get_analyst_cards -- new method for Analyst role
# ===========================================================

def get_analyst_cards(self):
    """Analysis-level cards for Analyst: Results Pending + To be Verified.

    Only active when the profile is installed in the current site.

    Returns a dict with ``title`` (translated section heading)
    and ``cards`` (list of card dicts) to support i18n in the JS.
    """
    empty = {"title": "Analyst", "cards": []}

    if not _is_installed(self):
        return empty

    user = api.get_current_user()
    if not user or "Analyst" not in user.getRoles():
        return empty

    base = {"portal_type": "Analysis", "is_active": True}
    cards = []

    # Results Pending = unassigned + assigned
    if self.has_permission(ViewResults):
        count = len(search(
            dict(base, review_state=["unassigned", "assigned"]),
            ANALYSIS_CATALOG))
        cards.append({
            "title": "Results Pending",
            "count": count,
            "url": "%s/samples?samples_review_state=sample_received"
                   % self.portal_url,
            "icon": "fa-flask",
        })

    # To be Verified
    # When self-verification is disabled, exclude analyses that were
    # submitted by the current user (they cannot verify themselves).
    if self.has_permission(TransitionVerify):
        brains = search(
            dict(base, review_state=["to_be_verified"]),
            ANALYSIS_CATALOG)
        current_user_id = user.getId()
        count = 0
        for brain in brains:
            analysis = api.get_object(brain)
            if analysis.isSelfVerificationEnabled():
                # self-verification allowed -- always include
                count += 1
            elif analysis.getSubmittedBy() != current_user_id:
                # not submitted by current user -- include
                count += 1
            # else: submitted by current user + self-verif disabled -> exclude
        cards.append({
            "title": "To be Verified",
            "count": count,
            "url": "%s/samples/@@samples-to-verify" % self.portal_url,
            "icon": "fa-check-circle",
        })

    return {"title": "Analyst", "cards": cards}


# ===========================================================
# 3. _panel -- add optional ``link`` parameter
# ===========================================================

_original_panel = DashboardView._panel


def _patched_panel(self, description, review_state,
                   listing_view, catalog, base_query, total,
                   link=None):
    """Build a simple statistics panel (extended with optional link).

    Backward-compatible: existing callers that don't pass ``link``
    get the original behaviour.
    """
    if not _is_installed(self):
        # Remove the extra ``link`` kwarg before calling original
        return _original_panel(
            self, description, review_state,
            listing_view, catalog, base_query, total)

    q = dict(base_query, review_state=[review_state])
    count = self._cached_count(q, catalog.id)

    if link is not None:
        link = "%s/%s" % (self.portal_url, link)
    elif listing_view:
        link = "%s/%s?%s_review_state=%s" % (
            self.portal_url, listing_view,
            listing_view, review_state)
    else:
        link = "#"

    return {
        "type": "simple-panel",
        "description": description,
        "number": count,
        "percentage": self._pct(count, total),
        "legend": self._legend(count, total),
        "link": link,
    }


# ===========================================================
# 4. _build_analyses_section -- pass link for "To be verified"
# ===========================================================

_original_build_analyses_section = DashboardView._build_analyses_section


def _patched_build_analyses_section(self):
    """Reuse the native Analyses section and only adjust one link."""
    if not _is_installed(self):
        return _original_build_analyses_section(self)
    section = _original_build_analyses_section(self)
    panels = section.get("panels", [])
    verify_link = "%s/samples/@@samples-to-verify" % self.portal_url
    for panel in panels:
        if panel.get("type") != "simple-panel":
            continue
        link = panel.get("link", "")
        if not link:
            continue
        if "to_be_verified" in link:
            panel["link"] = verify_link
            break
    return section


# ===========================================================
# Apply all patches (site-level gating is inside each method)
# ===========================================================

DashboardView.get_status_cards = _patched_get_status_cards
DashboardView.get_analyst_cards = get_analyst_cards
DashboardView._panel = _patched_panel
DashboardView._build_analyses_section = _patched_build_analyses_section

if "analyst_cards" not in SECTION_HANDLERS:
    SECTION_HANDLERS["analyst_cards"] = "get_analyst_cards"
