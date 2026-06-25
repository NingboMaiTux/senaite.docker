def setup_portal_title(context):
    """Set the portal title to  MaiTux LIMS  on install."""
    if context.readDataFile('medai.footercleanup.txt') is None:
        return
    site = context.getSite()
    site.setTitle('MaiTux LIMS')
