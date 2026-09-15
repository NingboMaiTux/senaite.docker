<#
.SYNOPSIS
    清理 addons\customers 下的孤儿 addon 目录。

.DESCRIPTION
    右键本文件「使用 PowerShell 运行」即可（Windows 双击 .ps1 是用记事本打开它，
    不是执行）。

    【解决什么问题】

    addon 从 git 删除后，本地会留下一个空壳目录。原因：容器把
    addons\customers 以 bind mount 挂进去（docker-compose.yml），buildout 生成的
    *.egg-info 和 Python 2 生成的 *.pyc 都会写回宿主机磁盘；而这两类文件在
    .gitignore 里，git 从不跟踪，所以 git 删掉源码时删不掉它们。
    目录里还剩着被忽略的文件 => 目录不空 => git 也不会清掉目录本身。

    结果就是一个「只剩 .pyc 和 .egg-info、没有任何源码」的假 addon 目录。

    【危害】

      * 容器不会加载它（gen-custom-addon.sh 只认带 setup.py 的目录），所以
        日常没有症状 —— 这正是它能长期潜伏的原因。
      * 打包.ps1 的 Copy-Tree 用 robocopy /E，排除 .pyc 后目录仍会被建成空目录
        打进交付包，实施同事看到会困惑。
      * 真正的雷：一旦有人把 setup.py 恢复回去（从旧分支 checkout、照别的 addon
        复制），立刻和现役 addon 提供同名 Python 包，两边的 overrides.zcml 注册
        同一个 adapter，ConfigurationConflictError，整站起不来。
      * Python 2 可以 import 没有 .py 的孤儿 .pyc（Py3 不行），所以残留的 .pyc
        不是纯粹的垃圾。

    【判据】三条全中才算孤儿，缺一不删：

      1. 是 addons\customers 的【一级子目录】（不递归进 addon 内部，不碰别的目录）
      2. git 【完全不跟踪】该目录下的任何文件（git ls-files 为空）
      3. 目录下【每一个文件都是构建产物】，且至少有一个文件

    第 3 条是安全底线，要点是「白名单反着用」：只有下面这三类算构建产物 ——

        *.pyc / *.pyo / *.pyd
        *.egg-info\ 目录里的任何文件
        __pycache__\ 目录里的任何文件

    除此之外的【任何】文件都算真实内容，一个都不能有。不认识的文件一律当成
    真实内容 —— 判断不了的时候选择不删。

    ★ 为什么不用「没有 .py 文件」当判据（第一版就是这么写的，是错的）：
      新 addon 完全可能只写了 configure.zcml、profiles\、模板 .pt 而还没写任何
      .py，它同样没被 git 跟踪 —— 按「没有 .py」判就会被当成孤儿删掉，
      那是手写的、没提交的活儿，删了找不回来。

    ★ 「至少有一个文件」：完全空的目录不删。它可能是谁刻意留的占位/挂载点，
      而且删它也收不回任何空间，报出来让人自己看就够了。

    【安全设计】

      * 默认只预览、不删除。确认无误后加 -Apply 才真删。
      * 删除前对每个目标【重新】核验一遍三条判据，不信任扫描阶段的结论。
      * 只在 addons\customers 一级子目录里找，路径写死，不接受任意目录。

.PARAMETER Apply
    真正执行删除。不给这个开关时只打印将要删什么，不动任何文件。

.PARAMETER Root
    项目目录（含 addons\customers 的那个）。默认取本脚本所在目录。

.PARAMETER NoPause
    结束后不等回车（脚本化调用时用）。

.PARAMETER Embedded
    被别的脚本调用时用（打包.ps1 就是这么调的）：隐去「加 -Apply 再跑一次」这类
    针对独立运行的提示，并隐含 -NoPause。删或不删由调用方决定，本脚本不再自己劝。

.EXAMPLE
    .\清理孤儿addon.ps1
    预览：列出所有孤儿目录，不删除。

.EXAMPLE
    .\清理孤儿addon.ps1 -Apply
    确认后真正删除。

.NOTES
    退出码（供 打包.ps1 这类调用方判断）：
        0  没有孤儿，或 -Apply 已删完
        1  出错（git 不可用、目录不存在等），什么都没做
        2  预览模式下发现了孤儿，但因为没给 -Apply 所以没删

    运行方式：右键「使用 PowerShell 运行」，或在 PowerShell 里 .\清理孤儿addon.ps1。
    机器执行策略拦住时用：
        powershell -NoProfile -ExecutionPolicy Bypass -File .\清理孤儿addon.ps1

    本文件必须保存为「带 BOM 的 UTF-8」。Windows PowerShell 5.1 会把没有 BOM
    的脚本按系统 ANSI 代码页解析，中文会变成乱码并导致语法错误。

    删掉的都是 git 不跟踪的构建产物，删错了也没有代码损失：重新跑一次容器
    就会重新生成 .pyc / .egg-info。真正不可逆的只有「目录本身消失」这一件事，
    而它本来就该消失。
#>

[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Root,
    [switch]$NoPause,
    [switch]$Embedded
)

$ErrorActionPreference = 'Stop'

# 被调用时一律不 pause：调用方的流程还没走完，卡在这里等回车没有意义。
if ($Embedded) { $NoPause = $true }

function Write-Note([string]$m) { Write-Host "  $m" -ForegroundColor DarkGray }
function Write-Ok  ([string]$m) { Write-Host "  $m" -ForegroundColor Green }
function Write-Warn([string]$m) { Write-Host "  $m" -ForegroundColor Yellow }
function Write-Err ([string]$m) { Write-Host "  $m" -ForegroundColor Red }

# ---------------------------------------------------------------- 定位目录 ----

if (-not $Root) { $Root = $PSScriptRoot }
if (-not $Root) { $Root = (Get-Location).Path }

$Customers = Join-Path $Root 'addons\customers'
if (-not (Test-Path -LiteralPath $Customers -PathType Container)) {
    Write-Err "找不到目录：$Customers"
    Write-Err '请把本脚本放在项目目录下（就是含 addons\customers 的那一级），或用 -Root 指定。'
    if (-not $NoPause) { Read-Host '按回车退出' }
    exit 1
}
$Customers = (Resolve-Path -LiteralPath $Customers).Path

# ------------------------------------------------------------------ git 检查 ----
#
# git 不可用就直接退出：判据 2 依赖 git，猜不得。宁可不清理，也不能凭
# 「看起来像垃圾」删目录。

try {
    $null = & git --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'git 不可用' }
} catch {
    Write-Err '找不到 git 命令，无法判断哪些目录还在版本控制里，已中止。'
    if (-not $NoPause) { Read-Host '按回车退出' }
    exit 1
}

try {
    $RepoRoot = (& git -C $Customers rev-parse --show-toplevel 2>&1) | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { throw 'not a repo' }
} catch {
    Write-Err "$Customers 不在 git 仓库里，已中止。"
    if (-not $NoPause) { Read-Host '按回车退出' }
    exit 1
}
$RepoRoot = $RepoRoot.Trim()

Write-Host ''
Write-Host 'MaiLIMS 孤儿 addon 清理' -ForegroundColor Cyan
Write-Host '================================================================'
Write-Note "git 仓库 : $RepoRoot"
Write-Note "扫描目录 : $Customers"
$branch = (& git -C $Customers rev-parse --abbrev-ref HEAD 2>$null) | Select-Object -First 1
Write-Note "当前分支 : $branch"
Write-Host ''

# ------------------------------------------------------------------- 判据 ----

# 判据 2：git 是否跟踪该目录下的任何文件。
# 返回 >=0 = 被跟踪的文件数；-1 = 问不出来（git 报错）。
#
# ★★ 「绝不删 git 里有的东西」这条铁律就落在这个函数上，两个要点： ★★
#
#  1.【fail-closed】git 只要非 0 退出就返回 -1。-1 不等于 0，IsOrphan 必然为假
#    => 保留。实测 git 对取不到的目录是「输出为空 + 退出码 128」，
#    原来那句 `if (-not $out) { return 0 }` 只看输出，会把报错读成
#    「0 个跟踪文件」=> 误删 git 里有的东西。判断不了时必须选择不删。
#
#  2.【不做相对路径换算】直接 git -C <该目录> ls-files，范围由 git 自己限定在
#    该目录内（实测 maitux.stock 得 119，与全仓库查询一致）。原先拿 $RepoRoot
#    的长度做 Substring 再拼 pathspec，有两个隐患：rev-parse 返回正斜杠而 .NET
#    给反斜杠，纯粹因为长度相等才没出错；且目录名里只要有 [ ] * ? ，
#    pathspec 会按通配符解释、匹配不到自己的文件 => 又是一次「查出 0 个」=> 误删。
function Get-TrackedCount([string]$DirFullPath) {
    $out  = & git -C $DirFullPath ls-files 2>$null
    $code = $LASTEXITCODE
    $global:LASTEXITCODE = 0
    if ($code -ne 0) { return -1 }
    if (-not $out)   { return 0 }
    return @($out).Count
}

# 判据 3 的核心：这个文件是不是构建产物？
# 白名单反着用 —— 只认这三类，其余一律当成真实内容（不认识就不删）。
function Test-BuildArtifact([System.IO.FileInfo]$File) {
    if ($File.Extension -in '.pyc', '.pyo', '.pyd') { return $true }
    if ($File.FullName -match '[\\/][^\\/]*\.egg-info[\\/]') { return $true }
    if ($File.FullName -match '[\\/]__pycache__[\\/]')       { return $true }
    return $false
}

# 三条判据的统一入口。删除前会再调一次，不复用扫描阶段的结论。
function Test-Orphan([System.IO.DirectoryInfo]$Dir) {
    $tracked = Get-TrackedCount $Dir.FullName
    # 目录本身是 junction / 符号链接：Remove-Item -Recurse 会顺着链接删到目标，
    # 而目标可能是仓库外的真实代码。一律不碰。
    $isLink  = (($Dir.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
    $files   = @(Get-ChildItem -LiteralPath $Dir.FullName -Recurse -File -Force -ErrorAction SilentlyContinue)
    $real    = @($files | Where-Object { -not (Test-BuildArtifact $_) })
    $bytes   = 0
    foreach ($f in $files) { $bytes += $f.Length }
    return [pscustomobject]@{
        Dir       = $Dir
        Tracked   = $tracked          # -1 = git 问不出来
        IsLink    = $isLink
        FileCount = $files.Count
        RealCount = $real.Count
        Real      = $real
        Bytes     = $bytes
        Files     = $files
        # 四条全中才删。注意 $tracked 为 -1（git 报错）时这里必然为假 => 保留。
        IsOrphan  = (($tracked -eq 0) -and (-not $isLink) -and
                     ($files.Count -gt 0) -and ($real.Count -eq 0))
    }
}

function Format-Size([long]$b) {
    if ($b -ge 1MB) { return ('{0:N1} MB' -f ($b / 1MB)) }
    if ($b -ge 1KB) { return ('{0:N0} KB' -f ($b / 1KB)) }
    return "$b B"
}

# 把残留文件按类型归类，让人一眼看出「确实只是构建产物」。
function Get-Breakdown($Files) {
    $pyc = 0; $egg = 0; $cache = 0; $other = 0
    foreach ($f in $Files) {
        if ($f.Extension -in '.pyc', '.pyo', '.pyd')      { $pyc++ }
        elseif ($f.FullName -match '\.egg-info[\\/]')     { $egg++ }
        elseif ($f.FullName -match '__pycache__[\\/]')    { $cache++ }
        else                                              { $other++ }
    }
    $parts = @()
    if ($pyc)   { $parts += "pyc $pyc" }
    if ($egg)   { $parts += "egg-info $egg" }
    if ($cache) { $parts += "pycache $cache" }
    if ($other) { $parts += "其他 $other" }
    if (-not $parts) { return '（空目录）' }
    return ($parts -join ' / ')
}

# -------------------------------------------------------------------- 扫描 ----

$orphans = @()
$keeps   = @()

foreach ($dir in (Get-ChildItem -LiteralPath $Customers -Directory -Force | Sort-Object Name)) {
    $r = Test-Orphan $dir
    if ($r.IsOrphan) { $orphans += $r } else { $keeps += $r }
}

# 保留项只报一行汇总，避免刷屏；真正要看的是孤儿清单。
Write-Host "保留 $($keeps.Count) 个目录（有源码或仍在版本控制里）：" -ForegroundColor Green
foreach ($k in $keeps) {
    $why = @()
    if ($k.RealCount -gt 0)  { $why += "$($k.RealCount) 个非构建产物文件" }
    if ($k.Tracked -gt 0)    { $why += "git 跟踪 $($k.Tracked) 个" }
    if ($k.Tracked -lt 0)    { $why += 'git 查询失败（按有跟踪处理）' }
    if ($k.IsLink)           { $why += '是符号链接/junction' }
    if ($k.FileCount -eq 0)  { $why += '空目录（不删）' }
    Write-Note ('{0,-36} {1}' -f $k.Dir.Name, ($why -join '，'))
    # git 问不出来是异常情况，不能混在正常「保留」里一句带过。
    if ($k.Tracked -lt 0) {
        Write-Err "  ^ git ls-files 在此目录上失败，无法确认是否被跟踪 —— 已保留，请人工确认"
    }
    # git 不跟踪、却有真实文件 => 多半是还没提交的新 addon，单独点名，
    # 免得有人看到它出现在清单里就以为脚本漏删了。
    if ($k.Tracked -eq 0 -and $k.RealCount -gt 0) {
        $sample = ($k.Real | Select-Object -First 3 | ForEach-Object { $_.Name }) -join '、'
        Write-Warn "  ^ 未提交但有真实文件（如 $sample），当作在写的新 addon 保留"
    }
}
Write-Host ''

if ($orphans.Count -eq 0) {
    Write-Ok '没有发现孤儿目录，无需清理。'
    Write-Host ''
    if (-not $NoPause) { Read-Host '按回车退出' }
    exit 0
}

$totalFiles = 0
$totalBytes = 0
foreach ($o in $orphans) { $totalFiles += $o.FileCount; $totalBytes += $o.Bytes }

Write-Host "发现 $($orphans.Count) 个孤儿目录：" -ForegroundColor Yellow
Write-Host ''
foreach ($o in $orphans) {
    Write-Host "  [孤儿] $($o.Dir.Name)" -ForegroundColor Yellow
    Write-Note "         git 跟踪     : 0 个文件"
    Write-Note "         非构建产物   : 0 个（全部 $($o.FileCount) 个文件都是构建产物）"
    Write-Note "         残留         : $($o.FileCount) 个文件 / $(Format-Size $o.Bytes)　（$(Get-Breakdown $o.Files)）"
}
Write-Host ''
Write-Host '----------------------------------------------------------------'
Write-Host "合计 $($orphans.Count) 个目录 / $totalFiles 个文件 / $(Format-Size $totalBytes)"
Write-Host ''

# -------------------------------------------------------------------- 删除 ----

if (-not $Apply) {
    Write-Warn '当前是【预览模式】，没有删除任何文件。'
    if (-not $Embedded) {
        Write-Host ''
        Write-Host '  确认上面的清单无误后，加 -Apply 执行删除：' -ForegroundColor Cyan
        Write-Host "      .\$(Split-Path -Leaf $PSCommandPath) -Apply" -ForegroundColor Cyan
    }
    Write-Host ''
    if (-not $NoPause) { Read-Host '按回车退出' }
    # 退出码 2 = 「发现了孤儿但没删」，供调用方判断要不要询问用户。
    # 0/1 沿用惯例：0 干净，1 出错。
    exit 2
}

Write-Host '开始删除……' -ForegroundColor Cyan
$done = 0
$failed = 0

foreach ($o in $orphans) {
    $name = $o.Dir.Name
    $full = $o.Dir.FullName

    # ---- 删除前重新核验，不信任扫描阶段的结论 ----------------------------
    # 扫描和删除之间可能过了很久（人在看清单），期间目录内容可能变了。
    # 三条判据任意一条不再成立就跳过，宁可不删。

    if (-not (Test-Path -LiteralPath $full -PathType Container)) {
        Write-Warn "$name ：目录已不存在，跳过"
        continue
    }
    # 路径必须仍在 customers 一级子目录下 —— 防符号链接/路径穿越
    $parent = (Split-Path -Parent $full)
    if ($parent -ne $Customers) {
        Write-Err "$name ：父目录不是 $Customers，跳过"
        $failed++
        continue
    }
    $recheck = Test-Orphan $o.Dir
    if (-not $recheck.IsOrphan) {
        Write-Err ("$name ：复核不通过（git 跟踪 {0} 个 / 非构建产物 {1} 个 / 共 {2} 个文件），跳过" `
                   -f $recheck.Tracked, $recheck.RealCount, $recheck.FileCount)
        $failed++
        continue
    }

    try {
        Remove-Item -LiteralPath $full -Recurse -Force
        Write-Ok "已删除 $name （$($o.FileCount) 个文件 / $(Format-Size $o.Bytes)）"
        $done++
    } catch {
        Write-Err "$name ：删除失败 —— $($_.Exception.Message)"
        $failed++
    }
}

Write-Host ''
Write-Host '----------------------------------------------------------------'
Write-Ok "完成：删除 $done 个目录"
if ($failed -gt 0) { Write-Warn "跳过/失败 $failed 个，见上面的原因" }
Write-Host ''
Write-Note 'git status 不会有任何变化 —— 删掉的都是未被跟踪的构建产物。'
Write-Note '容器无需重启：这些目录本来就不会被 gen-custom-addon.sh 加载。'
Write-Host ''

if (-not $NoPause) { Read-Host '按回车退出' }
