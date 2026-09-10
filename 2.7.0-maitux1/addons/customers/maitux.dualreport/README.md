# maitux.dualreport — 报告 PDF + Word 双格式输出（senaite.impress）

SENAITE 2.x（Plone 5.2 / Python 2.7）自研 add-on。在保留现有 PDF 管线不变
的前提下，让 **senaite.impress 报告发布/保存界面**可以按需输出 **Word(.docx)**：

- 报告模板（`.pt`）只产出 **HTML**；PDF 由代码里的 WeasyPrint 生成、Word 由
  本包用**同一份渲染后的 HTML** 生成 —— 因此两份文档的内容与版式同源，
  Word 尽可能贴近 PDF（字号、水平表格线、加粗标签、页脚页号、A4/页边距等）。
- 发布界面上新增“格式”下拉框（**PDF / Word**），作用于 **保存(Save)** 与
  **下载(Download PDF 图标)**：选 Word 时保存/下载的就是可编辑的 .docx。
- 一个报告对象（ResultsReport）只保存所选**一种**格式（复用现有 `pdf`
  文件字段，按格式写正确的文件名与 content-type），默认仍是 PDF，
  不影响旧行为。

> 结论先行（与仓库主 README 无关，这是本包自己的技术前提）：
> 输出文件由**代码**决定，模板只负责 HTML。所以本包不需要任何模板改动。

---

## 1. 功能与改动点（对核心代码是“补丁”而非改写）

所有集成均通过 import 期 monkey-patch 完成（与 `maitux.calcenhance` 同套路），
patch 内容收敛在 `src/maitux/dualreport/patches.py`：

| 核心目标 | patch 的方法 | 行为 |
|---|---|---|
| 保存时按所选格式入库 | `senaite.impress.ajax.AjaxPublishView.ajax_save_reports` | 读取 `report_format`（pdf/word）；Word 分支把该报告的 HTML 转成 docx 再 `storage.store(...)`，元数据带 `format: word`；Email 动作强制仍为 PDF |
| 下载/打印 Word | `senaite.impress.publishview.PublishView.download` | `report_format=word` 时返回 `.docx`（Content-Type/Disposition 正确），否则原 PDF 逻辑不变 |
| 入库 blob 名与类型正确 | `senaite.impress.storage.PdfReportStorageAdapter.create_report` | 按格式写 `xxx.docx` + docx content-type（仍存进 ResultsReport.pdf 字段） |
| 已存 Word 报告正确下载 | `bika.lims.browser.publish.downloadview.DownloadView.__call__` | 直接用 blob 自身的文件名/content-type；PDF inline、Word attachment |
| 报告列表正确显示格式 | `bika.lims.browser.publish.reports_listing.ReportsListingView.folderitem` | 存的是 Word 时列表列显示 “Word” |

前端不碰编译后的 impress bundle，而是走 senaite.impress 官方预留的扩展点：
`publish.pt` 会把资源类型 `senaite.impress.js` 下的 JS **内联**进发布页。
`resources/js/impress_dualformat.js` 做三件事：

1. 在发布工具栏（template/format/orientation 同一行）注入“格式”下拉框；
2. 通过 `window.impress`（发布 UI 主动暴露的句柄）给
   `getRequestOptions()` 追加 `report_format`，从而同时覆盖 Save/Download
   两条请求路径（含重新渲染后 DOM 变化，用 MutationObserver 保持）；
3. 下拉选 Word 时，把“下载 PDF”图标动作改为直接下载 Word 文件
   （避免先取 PDF blob 的旧流程），并兜底处理 docx 响应。

---

## 2. Word 生成器（零第三方依赖）

`src/maitux/dualreport/docx/`：

- `builder.py` — `HtmlToDocxConverter`：用 bs4 解析报告 HTML，按 senaite.impress
  报告 CSS 的语义映射成 WordprocessingML：
  - 基础字号 9pt（对应 `css.pt` 的 `.report * { font: 9pt }`），
    h1 140% / h2 120% / h3 110%、`.section-header h1` 175%、
    `.font-size-*`、`small/.figure-caption` 85% 等与 PDF 同一套缩放；
  - 表格默认只画**水平线**（上/下/行间，无竖线），与 PDF 的
    `td/th border-top/bottom` 观感一致；`noborder`/`range-table`/`border:none`
    单元格不带边框；`colgroup` 百分比列宽映射成 tblGrid；
  - `div.section-footer` 提取为 **Word 每页页脚**（上边框模拟 footer-line），
    右下角加 “第 X 页 / 共 Y 页” 域（PAGE/NUMPAGES，zh/en 可配）；
  - 图片：`data:` URI 直接嵌入，门户内部 URL 走与 WeasyPrint 相同的
    subrequest 抓取（logo/签名/附件）；SVG 与抓不到的外链图片跳过并记日志；
  - A4 页面/页边距/横纵向均取自发布流程同一套 paperformat 计算。
- `ooxml.py` — 纯 stdlib 拼 docx zip（[Content_Types]/rels/styles/footer/docProps）。
- `media.py` — data-URI 解析、PNG/JPEG/GIF 头部尺寸嗅探（96 DPI 兜底）。

零新增 egg 依赖：运行期只用到 **bs4**（senaite.impress 本来就有）。

---

## 3. 目录结构

```text
maitux.dualreport/
  setup.py                       # name=maitux.dualreport（egg 名，勿改目录名大小写）
  README.md
  src/maitux/__init__.py         # 命名空间
  src/maitux/dualreport/
    __init__.py                  # import 期 apply_patches（幂等，异常只记日志不崩站）
    config.py                    # 格式常量 / 字体 / 字号 / 页脚模板等调参点
    configure.zcml               # registerProfile(default/uninstall) + senaite.impress.js 资源
    patches.py                   # 全部 monkey-patch
    docx/{__init__,builder,ooxml,media}.py
    resources/js/impress_dualformat.js
    profiles/default|uninstall/  # 均含 metadata.xml（R4）
    tests/test_docx_smoke.py     # 脱离 Zope 的结构性自检
```

按开发规则清单核对：无 `overrides.zcml`（R1/R2/R5 不触发：configure 里没有
senaite 自定义权限、没有同名组件覆盖、没有跨 addon 同接口同名 adapter）；
分发名与目录名一致（R5c）；未手工维护 custom-addon.cfg（R5d）；
profile 目录真实存在（R4）；有 uninstall profile（非合规类，R4b 不适用）；
`registerProfile` 的 title 为 ASCII（R9b 不涉及 actions.xml，但保持 ASCII）。

---

## 4. 部署（按 SENAITE-Addon开发规则）

1. 把整个 `maitux.dualreport/` 放到
   `E:\senaite\docker\senaite.docker\2.7.0-maitux1\addons\customers\`
   **一级子目录**（该目录必须带 `setup.py`，gen-custom-addon.sh 才会收录；
   目录内不要再套一层客户目录）。
2. 重启容器让 buildout 收录新 egg（`docker compose logs instance |
   grep gen-custom-addon` 应能看到 maitux.dualreport 被收录）。
3. 后台 Add-ons 页面（`/prefs_install_products_form`）手工安装
   “Maitux Dual Report (PDF + Word)”。
   本包 profile 目前**不含** registry/类型等站点数据，无额外“重跑 profile”
   要求（R3）；以后若在 profile 里加内容，已装站点必须重跑 profile 或走
   upgrade step，不能依赖代码兜底。
4. `.py/.zcml` 改动需重启容器；**JS 改动需重启 + 浏览器硬刷新
   `Ctrl+Shift+R`**（发布页静态资源带长缓存头，R8）。
5. 本机自检（可选，需 py2 + bs4）：
   `python -m maitux.dualreport.tests.test_docx_smoke`
   （把包 `src/` 与 bs4 所在目录加入 PYTHONPATH）。

从其它环境同步用 `robocopy <源> <目标> /E /XF *.pyc /NFL /NDL /NJH /NJS`
（R7；退出码 0–7 均算成功）。

---

## 5. 验收判据（可观测信号，规则 R9 要求逐条可查）

| 检查项 | 可观测信号 |
|---|---|
| patch 已生效 | 实例日志出现 `maitux.dualreport: monkey-patches applied (download/save/storage/report-listing)` |
| patch 失败 | 日志出现 `maitux.dualreport: FAILED to apply patches: ...`（不会崩站，但功能缺失，必须处理） |
| 下拉框出现 | 发布页工具栏出现 “PDF ▾ / Word” 下拉（硬刷新后） |
| 保存 Word | 保存后进对应 AR，ResultsReport 的 pdf 字段 content-type 为 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`，元数据含 `format: word`；从 reports_listing 点下载得到 `*.docx` 且 Word 能打开 |
| 保存 PDF（默认/回归） | 与改造前完全一致：`*.pdf` + `application/pdf` |
| 下载 Word | 下拉选 Word 后点下载图标，浏览器直接下载 `.docx`（不再打开 PDF 预览） |
| 下载 PDF（回归） | 下拉默认 PDF 时下载图标行为不变（新标签打开 PDF） |
| Email | 邮件附件仍为 PDF（本包不改变邮件语义） |

## 6. “尽量一致”已达成与已知差异（如实声明）

达成（与 PDF 同源 HTML 映射）：A4/页边距/横纵向、9pt 基础字号与 % 缩放体系、
标题层级、水平表格线、label 加粗、左右对齐、页脚文本 + 页码域、图片嵌入
（同 WeasyPrint 的抓取通道）。

已知差异（Word 引擎所限，模板无需也不能消除）：
- 分页是 Word 流式重排，逐页断行与 PDF 不逐像素一致；
- PDF 的 `position:fixed` 页脚在 Word 里是“每页页脚”（内容相同但布局
  归 Word 管），超长页脚会被 Word 截断；
- 条形码/JS 生成的 SVG（barcode、图表）不嵌入 Word（跳过并记日志；
  PDF 走的是浏览器渲染后的位图/WeasyPrint，行为不同）；
- 默认字体：中文 宋体、西文 Arial（WeasyPrint 容器里是系统 CJK 字体），
  字号相同、字形可能略有差异；可在 `config.py` 调整；
- `colspan/rowspan` 未做网格合并（报告模板未使用）。

以上为尽力而为的工程取舍；如需逐像素一致，唯一出路是 LibreOffice 转档
（需改镜像装 soffice，见开发记录），本包按“零新依赖 + 零模板改动”交付。

## 7. 已知边界 / 后续

- 一个 ResultsReport 只保存**一种**格式；需要双份就分别用 PDF / Word 各保存一次。
- 邮件（Email）不提供 Word 选项，保持 PDF；从旧版 client 邮件页
  （emailview）发已存 Word 报告时附件名仍带 `.pdf` 后缀（本包未覆盖该入口，
  如需可另开需求）。
- 兼容性：只针对本镜像固定的 senaite.impress（buildout 里 rev=889778c…）
  的发布 UI 行为做适配；升级 senaite.impress 后应先跑一遍“验收判据”表。
