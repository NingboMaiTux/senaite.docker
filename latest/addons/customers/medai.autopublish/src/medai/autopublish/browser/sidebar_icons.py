from plone.app.layout.viewlets.common import ViewletBase


class SidebarIconsViewlet(ViewletBase):
    """Inject icons for custom sidebar folder links."""

    def render(self):
        return u"""
<style>
a.medai-sidebar-iconized {
  display: inline-flex;
  align-items: center;
}

.medai-sidebar-icon {
  width: 1.25rem;
  margin-right: 0.45rem;
  text-align: center;
  flex: 0 0 1.25rem;
}
</style>
<script>
(function() {
  var entries = [
    { suffix: '/analysis_reports', icon: 'fas fa-file-alt' },
    { suffix: '/samples-to-verify', icon: 'fas fa-vial' },
    { suffix: '/samples-to-approve', icon: 'fas fa-clipboard-check' }
  ];

  function matchLink(link, suffix) {
    if (!link || !link.getAttribute) {
      return false;
    }
    var href = link.getAttribute('href') || '';
    return href.slice(-suffix.length) === suffix ||
           href.slice(-(suffix.length + 1)) === suffix + '/';
  }

  function ensureIcons() {
    var links = document.getElementsByTagName('a');
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      if (link.getAttribute('data-medai-iconized') === '1') {
        continue;
      }
      for (var j = 0; j < entries.length; j++) {
        var entry = entries[j];
        if (!matchLink(link, entry.suffix)) {
          continue;
        }
        var icon = document.createElement('i');
        icon.className = entry.icon + ' medai-sidebar-icon';
        icon.setAttribute('aria-hidden', 'true');
        link.insertBefore(icon, link.firstChild);
        link.setAttribute('data-medai-iconized', '1');
        if (link.className.indexOf('medai-sidebar-iconized') === -1) {
          link.className += (link.className ? ' ' : '') + 'medai-sidebar-iconized';
        }
        break;
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureIcons);
  } else {
    ensureIcons();
  }

  window.setTimeout(ensureIcons, 500);
  window.setTimeout(ensureIcons, 1500);

  if (window.MutationObserver) {
    var observer = new MutationObserver(function() {
      ensureIcons();
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true
    });
  }
})();
</script>
"""
