# -*- coding: utf-8 -*-
"""profile v5 -> v6：S5 引入回填入口，需要一个新权限。

新增 `MAITUX: Backfill Audit Journal`，只给 Manager —— 回填是写操作，
一次可能写几万行，与"看流水"（给到 LabManager）刻意分开。

★ 为什么必须走 upgrade step 而不是"重装一次 profile"：本包按 R4b 豁免了
  卸载能力，代价就是**只剩升级一条路**，profile 的任何变更都得有 step，
  否则已装站点拿不到新权限，回填视图会 401 而没人知道为什么。
"""

import logging

logger = logging.getLogger("maitux.auditjournal")

PROFILE = "profile-maitux.auditjournal:default"


def upgrade(setup_tool):
    logger.warning("auditjournal: upgrade v5 -> v6, importing rolemap "
                   "(new permission: MAITUX: Backfill Audit Journal)")
    setup_tool.runImportStepFromProfile(PROFILE, "rolemap")
    logger.warning("auditjournal: upgrade v5 -> v6 finished")
