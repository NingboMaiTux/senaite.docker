<#
.SYNOPSIS
    labgate 打包工具 —— 交互式生成可交付的安装包。

.DESCRIPTION
    右键本文件「使用 PowerShell 运行」即可（Windows 双击 .ps1 是用记事本打开它，
    不是执行）。

    菜单三种模式：

      1  labgate 安装包    docker-compose.yml + .env + 文档，不含镜像
      2  labgate 镜像包    docker save 出可 docker load 的镜像归档
      3  完整交付          安装包 + 镜像打进同一个 zip（镜像只 ~20MB，一个文件
                          拷到客户机上双击 一键启动.cmd 就能跑）

    打包前自动更新：git pull 拉代码；docker pull 拉镜像（只在含镜像的模式做）。

    产物落在 dist\，每个产物旁边带一个 .sha256 校验文件。

    不打包源码：现场部署不编译，镜像由研发出好。要编译二进制见 build.ps1，
    要出镜像见 Makefile 的 docker-build / docker-push。

.PARAMETER Mode
    免交互指定模式（1-3）。不给则进菜单。

.PARAMETER ImageTag
    要打包的镜像 tag，默认取 .env（或 .env.example）里的 LABGATE_VERSION。
    包里 .env 的 LABGATE_VERSION 会被写成这个值，保证「compose 里写的 tag」和
    「实际交付的镜像 tag」一致 —— 这两个对不上是现场起不来的头号原因。

.PARAMETER OutputRoot
    产物输出目录，默认 <本目录>\dist。

.PARAMETER IncludeLocalEnv
    用本机的 .env 而不是从 .env.example 生成。**本机 .env 里有真实令牌和密码**，
    只在「就是要给这一台机器打一份现成配置」时用，且要确认交付渠道安全。

.PARAMETER Compress
    镜像归档额外做一遍 gzip。默认不做：docker save 出来的 OCI 归档里各层已经是
    压缩态，再 gzip 只小百分之几。

.PARAMETER SkipGitPull
    跳过 git pull。

.PARAMETER SkipDockerPull
    跳过 docker pull，直接用本机现有镜像。

.PARAMETER Yes
    所有确认一律按「是」，用于无人值守。

.PARAMETER NoPause
    结束后不等回车。

.EXAMPLE
    .\打包.ps1
    进菜单交互选择。

.EXAMPLE
    .\打包.ps1 -Mode 3 -ImageTag 1.0.0
    出一个包含 1.0.0 镜像的完整交付 zip。

.NOTES
    运行方式：右键「使用 PowerShell 运行」，或在 PowerShell 里 .\打包.ps1。
    机器执行策略拦住时用：
        powershell -NoProfile -ExecutionPolicy Bypass -File .\打包.ps1

    本文件必须保存为「带 BOM 的 UTF-8」。Windows PowerShell 5.1 会把没有 BOM
    的脚本按系统 ANSI 代码页解析，中文会变成乱码并导致语法错误。

    给实施人员的现场手册是仓库里的 部署说明.md，脚本会把它原样放进包内，不另
    写一份，免得两处说法不一致。

    维护提示：labgate 服务目前只依赖 docker-compose.yml + .env（数据都在命名卷
    labgate-data 里），所以包很干净。哪天 compose 加了宿主挂载（挂 config.json、
    证书之类），要同步在 New-LabgatePackage 里把对应文件拷进包。镜像引用是按
    服务名 labgate 从 compose 的 image: 行读的。
#>
[CmdletBinding()]
param(
    [ValidateSet('1', '2', '3')]
    [string]$Mode,
    [string]$ImageTag,
    [string]$OutputRoot,
    [switch]$IncludeLocalEnv,
    [switch]$Compress,
    [switch]$SkipGitPull,
    [switch]$SkipDockerPull,
    [switch]$Yes,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'

# 私有镜像仓库。docker pull / push 之前要先 docker login，用户名见下面这个常量，
# 密码人工输入（脚本里绝不存密码）。一台机器一般登录一次就一直有效。
$REGISTRY      = 'crpi-z99l88o2fu3lae8l.cn-hangzhou.personal.cr.aliyuncs.com'
$REGISTRY_USER = '厦门南乔'

#region ── 公共小工具 ────────────────────────────────────────────────────────
# 这一段和 2.7.0-maitux1\打包.ps1 里的同名函数是刻意重复的：两个目录各自是一份
# 独立交付物，谁都能单独拷走用，不为了去重引入跨目录依赖。

function Write-Step ([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok   ([string]$Text) { Write-Host "    [OK] $Text" -ForegroundColor Green }
function Write-Note ([string]$Text) { Write-Host "    $Text" -ForegroundColor Gray }
function Write-Warn2([string]$Text) { Write-Host "    [!] $Text" -ForegroundColor Yellow }

function Confirm-Continue([string]$Question) {
    if ($Yes) { return $true }
    $a = Read-Host "    $Question [y/N]"
    return ($a -eq 'y' -or $a -eq 'Y')
}

function Format-Size([long]$Bytes) {
    if ($Bytes -ge 1GB) { return ('{0:N2} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N1} MB' -f ($Bytes / 1MB)) }
    return ('{0:N0} KB' -f ($Bytes / 1KB))
}

function Expand-Template([string]$Text, [hashtable]$Map) {
    foreach ($k in $Map.Keys) { $Text = $Text.Replace('{{' + $k + '}}', [string]$Map[$k]) }
    return $Text
}

# 探测型的原生命令（docker image inspect、git rev-parse 之类，失败是正常分支）
# 一律走下面这两个包装。原因：Windows PowerShell 5.1 只要重定向了原生命令的
# stderr，就会把每行 stderr 包成 ErrorRecord，配合 $ErrorActionPreference='Stop'
# 直接抛异常 —— 「镜像不存在」这种预期内的失败会变成脚本崩溃。
#
# 其余非探测型调用（docker pull / docker save / git pull ...）刻意不重定向
# stderr：让报错原样显示给使用者，同时也不会触发上面这个坑。

function Invoke-Silent {
    param([string]$Exe, [string[]]$Arguments)
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $null = & $Exe @Arguments 2>&1
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
}

function Invoke-SilentOut {
    param([string]$Exe, [string[]]$Arguments)
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Exe @Arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return $out
    } finally {
        $ErrorActionPreference = $old
    }
}

function Test-Prerequisite {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw '找不到 docker。请先安装并启动 Docker Desktop。'
    }
    if ((Invoke-Silent 'docker' @('info', '--format', '{{.ServerVersion}}')) -ne 0) {
        throw 'Docker 没在运行（docker info 失败）。请启动 Docker Desktop 后重试。'
    }
    if ((Invoke-Silent 'docker' @('compose', 'version')) -ne 0) {
        throw 'docker compose（v2 插件）不可用。请升级 Docker Desktop。'
    }
}

# 是否已登录某个镜像仓库。只判断 config.json 的 auths 里有没有这个 key，不读也
# 不打印任何凭据内容（Docker Desktop 用 credsStore，密码根本不在这个文件里）。
function Test-RegistryLogin([string]$Registry) {
    $cfg = Join-Path $env:USERPROFILE '.docker\config.json'
    if (-not (Test-Path -LiteralPath $cfg)) { return $false }
    try {
        $json = Get-Content -LiteralPath $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $false
    }
    if (-not $json.auths) { return $false }
    return ($json.auths.PSObject.Properties.Name -contains $Registry)
}

# 没登录就登录。密码由使用者在 docker 自己的提示里手工输入，脚本不碰、不存。
function Connect-Registry([string]$Registry, [string]$User) {
    if (Test-RegistryLogin $Registry) {
        Write-Ok "已登录 $Registry"
        return
    }
    Write-Warn2 "尚未登录 $Registry，现在登录（密码请手工输入）"
    Write-Note "用户名：$User"
    & docker login --username=$User $Registry
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 '带用户名登录失败，改用 docker 自己问用户名的方式重试'
        Write-Note "提示 Username 时请输入：$User"
        & docker login $Registry
    }
    if ($LASTEXITCODE -ne 0) { throw 'docker login 失败，无法拉取私有镜像。' }
    Write-Ok '登录成功'
}

function Update-Repository([string]$RepoRoot) {
    if ($SkipGitPull) { Write-Warn2 '按参数跳过 git pull'; return }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Warn2 '找不到 git，跳过代码更新'
        return
    }

    $branch = Invoke-SilentOut 'git' @('-C', $RepoRoot, 'rev-parse', '--abbrev-ref', 'HEAD')
    Write-Note "仓库：$RepoRoot"
    Write-Note "分支：$branch"

    $dirty = @(Invoke-SilentOut 'git' @('-c', 'core.quotepath=false', '-C', $RepoRoot, 'status', '--porcelain'))
    if ($dirty.Count -gt 0) {
        Write-Warn2 "工作区有 $($dirty.Count) 处未提交改动（打进包里的是改动后的内容）"
        $dirty | Select-Object -First 8 | ForEach-Object { Write-Note "  $_" }
        if ($dirty.Count -gt 8) { Write-Note "  ...（其余 $($dirty.Count - 8) 处略）" }
    }

    if ($branch -and $branch -ne 'master') {
        Write-Warn2 '当前不在 master 分支，交付件通常应该从 master 打'
        if (-not (Confirm-Continue "确认继续用 $branch 分支打包？")) { throw '已取消。' }
    }

    & git -C $RepoRoot pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 'git pull 失败（常见原因：本地有改动、或需要 merge）'
        if (-not (Confirm-Continue '用当前工作区的代码继续打包？')) { throw '已取消。' }
    } else {
        Write-Ok '代码已是最新'
    }
}

function Test-ImageLocal([string]$Ref) {
    return ((Invoke-Silent 'docker' @('image', 'inspect', $Ref, '--format', '{{.Id}}')) -eq 0)
}

function Update-Image([string]$Ref) {
    if ($SkipDockerPull) { Write-Warn2 "按参数跳过 docker pull $Ref"; return }
    if ($Ref -like "$REGISTRY/*") { Connect-Registry $REGISTRY $REGISTRY_USER }

    Write-Note "docker pull $Ref"
    & docker pull $Ref
    if ($LASTEXITCODE -ne 0) {
        if (Test-ImageLocal $Ref) {
            Write-Warn2 "拉取失败，改用本机已有的 $Ref（注意：可能不是最新）"
        } else {
            throw "拉取 $Ref 失败，且本机没有这个镜像，无法继续。"
        }
    }
}

# 从 docker-compose.yml 里读各服务的镜像引用。单一事实来源就是 compose 文件，
# 脚本里不再抄一份镜像名，免得两边对不上。
function Get-ComposeImage {
    param([string]$ComposePath, [hashtable]$EnvMap = @{})

    $result = New-Object System.Collections.Specialized.OrderedDictionary
    $service = $null
    foreach ($line in (Get-Content -LiteralPath $ComposePath -Encoding UTF8)) {
        if ($line -match '^\s{2}([A-Za-z0-9_.\-]+):\s*$') { $service = $Matches[1]; continue }
        if ($service -and $line -match '^\s+image:\s*(\S+)\s*$') {
            $result[$service] = Expand-ComposeVariable $Matches[1] $EnvMap
            $service = $null
        }
    }
    return $result
}

function Expand-ComposeVariable([string]$Text, [hashtable]$EnvMap) {
    $rx = [regex]'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}'
    $evaluator = [System.Text.RegularExpressions.MatchEvaluator] {
        param($m)
        $name = $m.Groups[1].Value
        if ($EnvMap.ContainsKey($name) -and "$($EnvMap[$name])" -ne '') { return [string]$EnvMap[$name] }
        if ($m.Groups[2].Success) { return $m.Groups[2].Value }
        return ''
    }
    return $rx.Replace($Text, $evaluator)
}

function Read-DotEnv([string]$Path) {
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    foreach ($line in (Get-Content -LiteralPath $Path -Encoding UTF8)) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        $map[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim().Trim('"').Trim("'")
    }
    return $map
}

# 去掉 compose 里的 build: 段。交付包不含源码和 Dockerfile，留着 build 会让
# 「镜像不在本机」时 docker compose up 去尝试构建，然后报找不到 Dockerfile；
# 剥掉之后镜像缺失就是一句干净的 pull 报错。
function Remove-ComposeBuild([string[]]$Lines) {
    $out = New-Object System.Collections.Generic.List[string]
    $blockIndent = -1
    foreach ($line in $Lines) {
        if ($blockIndent -ge 0) {
            if ($line.Trim() -eq '') { continue }
            $indent = $line.Length - $line.TrimStart(' ').Length
            if ($indent -gt $blockIndent) { continue }
            $blockIndent = -1
        }
        if ($line -match '^(\s*)build:\s*$')  { $blockIndent = $Matches[1].Length; continue }
        if ($line -match '^(\s*)build:\s+\S') { continue }
        $out.Add($line)
    }
    return $out.ToArray()
}

# 用 docker compose config 校验产出的 compose + .env。语法错、必填变量没给
# （compose 里那些 ${VAR:?...}）都会在这里暴露，而不是等实施同事在客户现场发现。
function Test-ComposeFile([string]$Directory) {
    Push-Location $Directory
    try {
        & docker compose -f docker-compose.yml config -q
        if ($LASTEXITCODE -ne 0) { throw '包内 docker-compose.yml 校验失败，产物不可用。' }
    } finally {
        Pop-Location
    }
    Write-Ok '包内 docker-compose.yml + .env 校验通过（docker compose config）'
}

# 包内所有文本文件：不带 BOM 的 UTF-8、行尾 LF（跟仓库里现有 .md 一致）。
# BOM 会让 YAML 解析器直接报「found character that cannot start any token」。
# 唯一必须带 BOM 的是 .ps1 本身，那是 PS 5.1 的要求。
function Write-ConfFile([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, ($Text -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))
}

function Write-DocFile([string]$Path, [string]$Text) {
    Write-ConfFile $Path $Text
}

# .cmd 是给客户机上双击用的，内容保持纯 ASCII：cmd.exe 按控制台代码页读批处理
# 文件，中文在不同机器上会乱码甚至语法出错。行尾用 CRLF（批处理的老规矩）。
function Write-CmdFile([string]$Path, [string]$Text) {
    $t = ($Text -replace "`r`n", "`n") -replace "`n", "`r`n"
    [System.IO.File]::WriteAllText($Path, $t, (New-Object System.Text.ASCIIEncoding))
}

# 打 zip。条目名一律用正斜杠手工拼，不用 ZipFile::CreateFromDirectory ——
# .NET Framework 4.x 的那个方法会把条目名写成反斜杠（`目录\文件`），Linux 上
# unzip 出来就是一堆名字里带反斜杠的散文件，整个目录结构没了。zip 规范要求
# 正斜杠。顶层保留包目录名，解包出来是一个完整目录而不是散一地。
function New-ZipArchive([string]$SourceDir, [string]$OutFile) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $OutFile) { Remove-Item -LiteralPath $OutFile -Force }

    $base = Split-Path -Leaf $SourceDir
    $root = (Get-Item -LiteralPath $SourceDir).FullName.TrimEnd('\')
    $level = [System.IO.Compression.CompressionLevel]::Optimal
    $zip = [System.IO.Compression.ZipFile]::Open($OutFile, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        # -Force 是为了带上 .env 这种点开头的文件
        foreach ($f in (Get-ChildItem -LiteralPath $SourceDir -Recurse -File -Force)) {
            $rel = $f.FullName.Substring($root.Length + 1) -replace '\\', '/'
            $null = [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, $f.FullName, "$base/$rel", $level)
        }
        foreach ($d in (Get-ChildItem -LiteralPath $SourceDir -Recurse -Directory -Force)) {
            if (@(Get-ChildItem -LiteralPath $d.FullName -Force).Count -eq 0) {
                $rel = $d.FullName.Substring($root.Length + 1) -replace '\\', '/'
                $null = $zip.CreateEntry("$base/$rel/")
            }
        }
    } finally {
        $zip.Dispose()
    }
}

# docker save 导出镜像。-Compress 时把 docker 的 stdout 直接接到 GZipStream，
# 不落中间那个 tar。
function Export-DockerImage {
    param([string[]]$Refs, [string]$OutFile, [switch]$Gzip)

    if (-not $Gzip) {
        & docker save -o $OutFile @Refs
        if ($LASTEXITCODE -ne 0) { throw "docker save 失败（退出码 $LASTEXITCODE）" }
        return
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = (Get-Command docker).Source
    $psi.Arguments = ((@('save') + $Refs) | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = [System.Diagnostics.Process]::Start($psi)
    # stderr 必须并行读掉，否则管道写满会把 docker 卡死
    $stderr = $proc.StandardError.ReadToEndAsync()
    $fs = [System.IO.File]::Create($OutFile)
    try {
        $gz = New-Object System.IO.Compression.GZipStream($fs, [System.IO.Compression.CompressionLevel]::Optimal)
        $buffer = New-Object byte[] (4MB)
        while (($n = $proc.StandardOutput.BaseStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $gz.Write($buffer, 0, $n)
        }
        $gz.Dispose()
    } finally {
        $fs.Dispose()
    }
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) {
        Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
        throw "docker save 失败：$($stderr.Result)"
    }
}

# 产物旁边放一个 sha256sum 兼容的校验文件（两个空格分隔）
function New-Checksum([string]$FilePath) {
    $hash = (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLower()
    Write-ConfFile "$FilePath.sha256" ("{0}  {1}`n" -f $hash, (Split-Path -Leaf $FilePath))
    return $hash
}

function Get-UniquePath([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $Path }
    $dir  = Split-Path -Parent $Path
    $leaf = Split-Path -Leaf $Path
    $ext = ''
    foreach ($e in @('.tar.gz', '.tar', '.zip')) {
        if ($leaf.EndsWith($e)) { $ext = $e; break }
    }
    $base = if ($ext) { $leaf.Substring(0, $leaf.Length - $ext.Length) } else { $leaf }
    return (Join-Path $dir ('{0}-{1}{2}' -f $base, (Get-Date -Format 'HHmmss'), $ext))
}

$script:Artifacts = @()
function Add-Artifact([string]$Path) {
    $item = Get-Item -LiteralPath $Path
    $hash = New-Checksum $Path
    $script:Artifacts += [pscustomobject]@{ Name = $item.Name; Size = $item.Length; Sha256 = $hash }
}

function Get-GitInfo([string]$RepoRoot) {
    $info = [ordered]@{ Commit = '(未知)'; Branch = '(未知)'; Date = '(未知)'; Dirty = '(未知)' }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { return $info }
    $info.Commit = Invoke-SilentOut 'git' @('-C', $RepoRoot, 'rev-parse', '--short', 'HEAD')
    $info.Branch = Invoke-SilentOut 'git' @('-C', $RepoRoot, 'rev-parse', '--abbrev-ref', 'HEAD')
    $info.Date   = Invoke-SilentOut 'git' @('-C', $RepoRoot, 'log', '-1', '--format=%cd', '--date=format:%Y-%m-%d %H:%M:%S')
    $n = @(Invoke-SilentOut 'git' @('-c', 'core.quotepath=false', '-C', $RepoRoot, 'status', '--porcelain')).Count
    $info.Dirty = if ($n -eq 0) { '干净' } else { "有 $n 处未提交改动" }
    return $info
}
#endregion

#region ── .env 处理 ────────────────────────────────────────────────────────

# 生成包内的 .env。
#
# 默认从 .env.example 生成，只把 LABGATE_VERSION 改成实际交付的镜像 tag ——
# 其余项是 change-me 之类的占位值，由实施同事按现场改（部署说明.md 第一步）。
# 这样做的原因：本机 .env 里是研发环境的真实令牌和管理密码，不该跟着交付件走。
# 确实需要带本机 .env 时用 -IncludeLocalEnv。
function New-PackageEnv {
    param([string]$Destination, [string]$Tag)

    $localEnv   = Join-Path $script:Root '.env'
    $exampleEnv = Join-Path $script:Root '.env.example'

    if ($IncludeLocalEnv) {
        if (-not (Test-Path -LiteralPath $localEnv)) { throw '本机没有 .env，无法 -IncludeLocalEnv。' }
        Write-Warn2 '按参数打包本机 .env —— 里面有真实令牌与管理密码，注意交付渠道'
        if (-not (Confirm-Continue '确认把本机 .env 放进交付包？')) { throw '已取消。' }
        $source = $localEnv
    } else {
        if (-not (Test-Path -LiteralPath $exampleEnv)) { throw '找不到 .env.example，无法生成包内 .env。' }
        $source = $exampleEnv
    }

    # 逐行替换 LABGATE_VERSION，其余原样保留（注释也留着，现场要照着改）
    $lines = Get-Content -LiteralPath $source -Encoding UTF8
    $done = $false
    $out = foreach ($line in $lines) {
        if ($line -match '^\s*LABGATE_VERSION\s*=') {
            $done = $true
            "LABGATE_VERSION=$Tag"
        } else {
            $line
        }
    }
    if (-not $done) { $out = @($out) + @("LABGATE_VERSION=$Tag") }

    Write-ConfFile $Destination (($out -join "`n") + "`n")
    Write-Ok "包内 .env 已生成（LABGATE_VERSION=$Tag$(if ($IncludeLocalEnv) { '，源自本机 .env' } else { '，源自 .env.example' })）"
}

# 交付用的镜像 tag：参数 > .env > .env.example > dev
function Resolve-ImageTag {
    if ($ImageTag) { return $ImageTag }
    foreach ($f in @('.env', '.env.example')) {
        $map = Read-DotEnv (Join-Path $script:Root $f)
        if ($map.ContainsKey('LABGATE_VERSION') -and $map['LABGATE_VERSION']) { return $map['LABGATE_VERSION'] }
    }
    return 'dev'
}
#endregion

#region ── 生成的文档内容 ───────────────────────────────────────────────────
# 模板一律用单引号 here-string：里面有 markdown 反引号和 shell 的 $()，用双引号
# here-string 会被 PowerShell 当转义符和变量吃掉。变量靠 {{占位符}} 替。

function Get-QuickStartCmd {
    # 纯 ASCII：见 Write-CmdFile 的说明
    return @'
@echo off
rem ---------------------------------------------------------------------------
rem  labgate quick start (double-click me on the lab PC)
rem
rem  1. loads labgate-*.tar / *.tar.gz in this folder into Docker, if present
rem  2. docker compose up -d
rem  3. prints the admin UI address
rem
rem  Edit .env first - see the deployment guide (the .md files in this folder).
rem  ASCII only on purpose: cmd.exe reads batch files in the console code page.
rem ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ===============================================
echo  labgate quick start
echo ===============================================

where docker >nul 2>nul
if errorlevel 1 (
    echo [ERROR] docker not found. Install/start Docker Desktop first.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env not found next to this file.
    echo Copy .env.example to .env and fill in the site values first.
    pause
    exit /b 1
)

for %%f in (labgate-image-*.tar labgate-image-*.tar.gz) do (
    echo.
    echo ==^> docker load -i %%f
    docker load -i "%%f"
    if errorlevel 1 (
        echo [ERROR] docker load failed.
        pause
        exit /b 1
    )
)

set PORT=8090
for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
    if /i "%%a"=="LABGATE_PORT" set PORT=%%b
)

echo.
echo ==^> docker compose up -d
docker compose up -d
if errorlevel 1 (
    echo [ERROR] compose failed. Check .env values, then run: docker compose logs
    pause
    exit /b 1
)

echo.
echo ==^> docker compose ps
docker compose ps

echo.
echo Admin UI:  http://localhost:!PORT!
echo Logs:      docker compose logs -f labgate
echo Stop:      docker compose down
echo.
pause
'@
}

function Get-LabgateReadme {
    $tpl = @'
# labgate 安装包速查（{{TAG}}）

本包是**不含源码**的交付件：现场不编译，镜像由研发出好。

打包时间：{{DATE}}　　代码版本：{{COMMIT}}（{{BRANCH}}）

完整的现场手册见同目录 **部署说明.md**（配置项含义、离线导入、排错都在那里）。
本文件只是「这一包里有什么、怎么最快跑起来」。

## 包内容

| 文件 | 说明 |
|---|---|
| `docker-compose.yml` | 编排文件，已剥离 build 段（直接用现成镜像，不在现场构建） |
| `.env` | 现场配置。**必改 4 项**，见下 |
| `.env.example` | 配置模板原件，留着对照注释 |
| `一键启动.cmd` | Windows 上双击：导入镜像 + compose up -d |
| `部署说明.md` | 给实施人员的完整手册 |
| `版本信息.txt` | 版本号、镜像 ID、git 提交 |
{{IMAGE_ROW}}

## 需要的镜像

    {{IMAGE_REF}}

`.env` 里的 `LABGATE_VERSION` 已经写成 **{{TAG}}**，和交付的镜像 tag 一致，不要
再改它 —— 这两个对不上是现场起不来的头号原因。

## 最快跑起来

1. 把整个目录拷到实验室电脑上（Docker Desktop 要先装好并启动）。

2. 用记事本打开 `.env`，改这 4 项：

   | 变量 | 填什么 |
   |---|---|
   | `LABGATE_LIMS_URL` | LIMS 地址，如 `http://192.168.1.18:8081/lims` |
   | `LABGATE_LIMS_TOKEN` | LIMS「中转站」模板上登记的 `agent_token`，一个中转站一个 |
   | `LABGATE_ADMIN_PASSWORD` | 管理界面登录密码，一客户一密码，别留 `change-me` |
   | `LABGATE_HOST_LAN_IP` | 天平/串口网关装在本机时，填本机局域网 IP |

3. 双击 `一键启动.cmd`。

4. 浏览器打开 `http://localhost:{{PORT}}`（端口即 `.env` 里的 `LABGATE_PORT`）。

命令行等价操作：

    docker load -i labgate-image-{{TAG}}-*.tar    # 有镜像包时
    docker compose up -d
    docker compose logs -f labgate

没有镜像包时改为在线拉（需先登录仓库，账号问研发）：

    docker login {{REGISTRY}}
    docker compose pull

## 注意

- `.env` 里有密码和令牌，**不要发到群里、不要提交到代码仓库**。
- 本包里的 `.env` 是模板值（`change-me`），照上表改完再启动。
- 配置和 JetStream 落盘数据都在命名卷 `labgate-data` 里，容器重建不丢；
  `docker compose down -v` 会连数据一起删，慎用。
'@
    $imageRow = if ($script:BundledImage) {
        '| `' + $script:BundledImage + '` | labgate 镜像归档，一键启动.cmd 会自动 docker load |'
    } else {
        '| （镜像另外交付，或在线 docker compose pull） | |'
    }
    return (Expand-Template $tpl @{
        TAG       = $script:Tag
        DATE      = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        COMMIT    = $script:Git.Commit
        BRANCH    = $script:Git.Branch
        IMAGE_REF = $script:ImageRef
        IMAGE_ROW = $imageRow
        REGISTRY  = $REGISTRY
        PORT      = $script:Port
    })
}

function New-VersionFile([string]$Path, [string]$Kind) {
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine('labgate 交付件版本信息')
    [void]$sb.AppendLine('================================================')
    [void]$sb.AppendLine("包类型      : $Kind")
    [void]$sb.AppendLine("镜像 tag    : $script:Tag")
    [void]$sb.AppendLine("镜像        : $script:ImageRef")
    if (Test-ImageLocal $script:ImageRef) {
        [void]$sb.AppendLine("镜像 ID     : $(& docker image inspect $script:ImageRef --format '{{.Id}}')")
        [void]$sb.AppendLine("镜像创建于  : $(& docker image inspect $script:ImageRef --format '{{.Created}}')")
    }
    [void]$sb.AppendLine("打包时间    : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    [void]$sb.AppendLine("打包机器    : $env:COMPUTERNAME / $env:USERNAME")
    [void]$sb.AppendLine("git 提交    : $($script:Git.Commit)  ($($script:Git.Branch))")
    [void]$sb.AppendLine("提交时间    : $($script:Git.Date)")
    [void]$sb.AppendLine("工作区状态  : $($script:Git.Dirty)")
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine('核对方法（客户机上）：')
    [void]$sb.AppendLine('    docker images       # tag 应与上面一致')
    [void]$sb.AppendLine('    docker compose ps   # labgate 应为 running')
    Write-DocFile $Path $sb.ToString()
}
#endregion

#region ── 各模式的打包实现 ─────────────────────────────────────────────────

# 模式 1 / 3：安装包。$BundleImage 为真时把镜像归档一并放进包里（模式 3）。
function New-LabgatePackage {
    param([switch]$BundleImage)

    Write-Step $(if ($BundleImage) { '打完整交付包（含镜像）' } else { '打 labgate 安装包（不含镜像）' })

    # 产物文件名刻意保持纯 ASCII：交付件要过邮件、U 盘、跳板机，中文名在这些环节
    # 上最容易被改坏。包内的文档文件名照旧用中文。
    $name = "labgate-$script:Tag-$script:Stamp"
    if ($BundleImage) { $name = "labgate-full-$script:Tag-$script:Stamp" }
    $stage = Join-Path $script:StagingRoot $name
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null

    # compose：剥掉 build 段（包里没有源码和 Dockerfile）
    $lines = Get-Content -LiteralPath (Join-Path $script:Root 'docker-compose.yml') -Encoding UTF8
    Write-ConfFile (Join-Path $stage 'docker-compose.yml') (((Remove-ComposeBuild $lines) -join "`n") + "`n")
    Write-Ok 'docker-compose.yml 已剥离 build 段（改用现成镜像）'

    New-PackageEnv -Destination (Join-Path $stage '.env') -Tag $script:Tag
    Copy-Item -LiteralPath (Join-Path $script:Root '.env.example') -Destination (Join-Path $stage '.env.example')

    # 现场手册用仓库里那份现成的，不另写一份免得两处说法不一致
    $guide = Join-Path $script:Root '部署说明.md'
    if (Test-Path -LiteralPath $guide) {
        Copy-Item -LiteralPath $guide -Destination (Join-Path $stage '部署说明.md')
        Write-Ok '部署说明.md 已打入包内'
    } else {
        Write-Warn2 '仓库里没有 部署说明.md，包内只有速查版 安装说明.md'
    }

    $script:BundledImage = $null
    if ($BundleImage) {
        $imgFile = "labgate-image-$script:Tag-$script:Stamp" + $(if ($Compress) { '.tar.gz' } else { '.tar' })
        Export-ImageTo -OutFile (Join-Path $stage $imgFile)
        $script:BundledImage = $imgFile
    }

    Write-CmdFile (Join-Path $stage '一键启动.cmd') (Get-QuickStartCmd)
    New-VersionFile (Join-Path $stage '版本信息.txt') $(if ($BundleImage) { '完整交付（安装包 + 镜像）' } else { '安装包（不含镜像）' })
    Write-DocFile (Join-Path $stage '安装说明.md') (Get-LabgateReadme)

    Test-ComposeFile $stage

    $out = Get-UniquePath (Join-Path $script:OutDir "$name.zip")
    Write-Note '压缩成 zip（现场多是 Windows 电脑，zip 双击就能解）'
    New-ZipArchive $stage $out
    Add-Artifact $out
    Remove-Item -LiteralPath $stage -Recurse -Force
}

# 把镜像导出到指定文件（含 pull、空间检查）
function Export-ImageTo([string]$OutFile) {
    Update-Image $script:ImageRef
    if (-not (Test-ImageLocal $script:ImageRef)) { throw "本机没有镜像 $script:ImageRef，无法导出。" }

    $need = [long](& docker image inspect $script:ImageRef --format '{{.Size}}')
    $qualifier = (Split-Path -Qualifier $script:OutDir).TrimEnd(':')
    $drive = Get-PSDrive -Name $qualifier -ErrorAction SilentlyContinue
    if ($drive -and $drive.Free -lt ($need * 1.3)) {
        Write-Warn2 ('输出盘剩余 {0}，本次约需 {1}，可能不够' -f (Format-Size $drive.Free), (Format-Size $need))
        if (-not (Confirm-Continue '继续？')) { throw '已取消。' }
    }

    Write-Note ('docker save {0}（约 {1}）' -f $script:ImageRef, (Format-Size $need))
    Export-DockerImage -Refs @($script:ImageRef) -OutFile $OutFile -Gzip:$Compress
    Write-Ok "镜像已导出：$(Split-Path -Leaf $OutFile)"
}

# 模式 2：只出镜像
function New-ImagePackage {
    Write-Step '导出 labgate 镜像'

    $ext = if ($Compress) { '.tar.gz' } else { '.tar' }
    $out = Get-UniquePath (Join-Path $script:OutDir "labgate-image-$script:Tag-$script:Stamp$ext")
    Export-ImageTo -OutFile $out
    Add-Artifact $out

    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine('labgate 镜像包')
    [void]$sb.AppendLine('================================================')
    [void]$sb.AppendLine("归档文件  : $(Split-Path -Leaf $out)")
    [void]$sb.AppendLine("镜像      : $script:ImageRef")
    [void]$sb.AppendLine("镜像 ID   : $(& docker image inspect $script:ImageRef --format '{{.Id}}')")
    [void]$sb.AppendLine("打包时间  : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    [void]$sb.AppendLine("git 提交  : $($script:Git.Commit)  ($($script:Git.Branch))")
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine('导入方法（客户机上，与归档文件同目录执行）：')
    [void]$sb.AppendLine("    docker load -i $(Split-Path -Leaf $out)")
    [void]$sb.AppendLine('    docker images        # 核对 tag 与上面一致')
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine("注意：.env 里的 LABGATE_VERSION 必须等于 $script:Tag，否则 compose 找不到镜像。")
    Write-DocFile (Join-Path $script:OutDir ((Split-Path -Leaf $out) + '.清单.txt')) $sb.ToString()
}
#endregion

#region ── 主流程 ───────────────────────────────────────────────────────────

function Show-Banner {
    Write-Host ''
    Write-Host '  ============================================' -ForegroundColor DarkCyan
    Write-Host '   labgate 打包工具' -ForegroundColor White
    Write-Host "   目录：$script:Root" -ForegroundColor DarkGray
    Write-Host '  ============================================' -ForegroundColor DarkCyan
}

function Show-Menu {
    Write-Host ''
    Write-Host '  请选择打包模式：' -ForegroundColor White
    Write-Host ''
    Write-Host '   1  labgate 安装包      ' -NoNewline -ForegroundColor Yellow
    Write-Host 'compose + .env + 文档，不含镜像'
    Write-Host '   2  labgate 镜像        ' -NoNewline -ForegroundColor Yellow
    Write-Host '只导出镜像归档'
    Write-Host '   3  完整交付            ' -NoNewline -ForegroundColor Yellow
    Write-Host '安装包 + 镜像打进同一个 zip'
    Write-Host ''
    Write-Host '   0  退出' -ForegroundColor DarkGray
    Write-Host ''
    while ($true) {
        $sel = (Read-Host '  输入序号').Trim()
        if ($sel -eq '0' -or $sel -eq 'q') { return $null }
        if ($sel -match '^[1-3]$') { return $sel }
        Write-Host '  无效输入，请输入 0-3' -ForegroundColor Red
    }
}

try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

$script:Root = $PSScriptRoot
if (-not $script:Root) { $script:Root = Split-Path -Parent $MyInvocation.MyCommand.Definition }

$exitCode = 0
try {
    Show-Banner

    $selected = if ($Mode) { $Mode } else { Show-Menu }
    if (-not $selected) { Write-Host ''; Write-Host '  已退出。' -ForegroundColor DarkGray; return }

    Write-Step '环境检查'
    Test-Prerequisite
    Write-Ok "docker $(& docker info --format '{{.ServerVersion}}')，compose $(& docker compose version --short)"

    $script:RepoRoot = Invoke-SilentOut 'git' @('-C', $script:Root, 'rev-parse', '--show-toplevel')
    if (-not $script:RepoRoot) { $script:RepoRoot = Split-Path -Parent $script:Root }

    Write-Step '更新代码（git pull）'
    Update-Repository $script:RepoRoot
    $script:Git = Get-GitInfo $script:RepoRoot

    $script:Tag = Resolve-ImageTag
    $script:Stamp = Get-Date -Format 'yyyyMMdd'

    # 镜像引用从 compose 里读，${LABGATE_VERSION:-dev} 用上面定下来的 tag 展开
    $envMap = Read-DotEnv (Join-Path $script:Root '.env')
    $envMap['LABGATE_VERSION'] = $script:Tag
    $images = Get-ComposeImage -ComposePath (Join-Path $script:Root 'docker-compose.yml') -EnvMap $envMap
    $script:ImageRef = $images['labgate']
    if (-not $script:ImageRef) { throw 'docker-compose.yml 里没找到 labgate 服务的 image。' }

    $script:Port = '8090'
    $portMap = Read-DotEnv (Join-Path $script:Root '.env.example')
    if ($portMap.ContainsKey('LABGATE_PORT') -and $portMap['LABGATE_PORT']) { $script:Port = $portMap['LABGATE_PORT'] }

    Write-Note "镜像 tag：$script:Tag"
    Write-Note "镜像：$script:ImageRef"
    if ($script:Tag -eq 'dev') {
        Write-Warn2 '当前 tag 是 dev。正式交付建议用版本号，例如：.\打包.ps1 -ImageTag 1.0.0'
    }

    $script:OutDir = if ($OutputRoot) { $OutputRoot } else { Join-Path $script:Root 'dist' }
    $script:StagingRoot = Join-Path $script:OutDir '.staging'
    New-Item -ItemType Directory -Force -Path $script:StagingRoot | Out-Null

    switch ($selected) {
        '1' { New-LabgatePackage }
        '2' { New-ImagePackage }
        '3' { New-LabgatePackage -BundleImage }
    }

    Write-Step '完成'
    Write-Host "    输出目录：$script:OutDir" -ForegroundColor White
    Write-Host ''
    foreach ($a in $script:Artifacts) {
        Write-Host ('    {0,-52} {1,10}' -f $a.Name, (Format-Size $a.Size)) -ForegroundColor Green
        Write-Host ('      sha256 {0}...' -f $a.Sha256.Substring(0, 16)) -ForegroundColor DarkGray
    }
    Write-Host ''
    Write-Note '每个产物旁有同名 .sha256'
    Write-Note '交付前请核对 版本信息.txt 里的镜像 tag 与 ID'
} catch {
    $exitCode = 1
    Write-Host ''
    Write-Host "  打包失败：$($_.Exception.Message)" -ForegroundColor Red
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
} finally {
    if ($script:StagingRoot -and (Test-Path -LiteralPath $script:StagingRoot)) {
        Remove-Item -LiteralPath $script:StagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not $NoPause) {
        Write-Host ''
        Read-Host '  按回车关闭' | Out-Null
    }
}
exit $exitCode
#endregion
