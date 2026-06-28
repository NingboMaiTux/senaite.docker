import logging


logger = logging.getLogger("maitux.clientcompany")


def _patch_client_folder_listing():
    try:
        import collections
        from bika.lims import api
        from bika.lims import bikaMessageFactory as _
        from bika.lims.browser import clientfolder as clientfolder_module
    except Exception:
        logger.exception("Failed to import client folder modules for patching")
        return

    view_class = getattr(clientfolder_module, "ClientFolderContentsView", None)
    if view_class is None:
        logger.warning("ClientFolderContentsView not found for patching")
        return

    if getattr(view_class, "_maitux_clientcompany_patched", False):
        return

    original_init = view_class.__init__
    original_folderitem = view_class.folderitem

    def patched_init(self, context, request):
        original_init(self, context, request)

        columns = collections.OrderedDict()
        inserted = False
        for key, value in self.columns.items():
            columns[key] = value
            if key == "ClientID":
                columns["Company"] = {
                    "title": _("Company"),
                    "sortable": False,
                }
                inserted = True

        if not inserted:
            columns["Company"] = {
                "title": _("Company"),
                "sortable": False,
            }

        self.columns = columns
        for review_state in self.review_states:
            review_state["columns"] = list(self.columns.keys())

    def patched_folderitem(self, obj, item, index):
        item = original_folderitem(self, obj, item, index)
        try:
            obj = api.get_object(obj)
            field = obj.Schema().get("Company")
            company = field.get(obj) if field else ""
        except Exception:
            company = ""
        item["Company"] = company or ""
        return item

    view_class.__init__ = patched_init
    view_class.folderitem = patched_folderitem
    view_class._maitux_clientcompany_patched = True
    logger.info("Patched ClientFolderContentsView for Company column")

_patch_client_folder_listing()
