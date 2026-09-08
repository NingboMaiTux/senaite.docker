<#
.SYNOPSIS
    MaiLIMS 打包工具 —— 交互式生成可交付的安装包。

.DESCRIPTION
    右键本文件「使用 PowerShell 运行」即可（Windows 双击 .ps1 是用记事本打开它，
    不是执行）。

    菜单五种模式：

      1  Addon 安装包        只打 addons/customers，实施同事直接覆盖生产目录
      2  LIMS 安装包         docker-compose.yml + nginx + addons，不含镜像
      3  maitux-lims 镜像包  docker save 出可 docker load 的镜像归档
      4  全部镜像            lims + nginx + postgres，一个归档
      5  完整交付            2 + 4，新装一台机器要的东西一次给全

    打包前自动更新：git pull 拉代码；docker pull 拉镜像（只在含镜像的模式做 ——
    模式 1/2 的产物里没有镜像，拉 1GB 没意义）。

    产物落在 dist\，每个产物旁边带一个 .sha256 校验文件（Linux 上可
    sha256sum -c 直接验）。

.PARAMETER Mode
    免交互指定模式（1-5）。不给则进菜单。

.PARAMETER Version
    版本号，默认取本目录名（如 2.7.0-maitux1）。只影响产物文件名和版本信息.txt，
    不改 docker-compose.yml 里的镜像 tag。

.PARAMETER OutputRoot
    产物输出目录，默认 <本目录>\dist。

.PARAMETER Compress
    镜像归档额外做一遍 gzip（.tar -> .tar.gz）。默认不做：本机 Docker 用的是
    containerd 镜像库，docker save 出来的 OCI 归档里各层已经是压缩态，实测再
    gzip 只小 4%（66MB -> 63MB）却要多花几十秒，不值。

.PARAMETER SeparateImages
    模式 4 里每个镜像单独出一个归档，而不是三个打进一个。

.PARAMETER IncludeDevFiles
    Addon 包里保留 customers 根目录下的开发件（lint_addon.py、selftest_*.py、
    开发规则.md、摘要.xlsx 等）。默认剔除 —— 交付给客户的包里不该有这些。

.PARAMETER SkipGitPull
    跳过 git pull（离线，或者刻意要打当前工作区的代码时用）。

.PARAMETER SkipDockerPull
    跳过 docker pull，直接用本机现有镜像。

.PARAMETER Yes
    所有确认一律按「是」，用于无人值守。

.PARAMETER NoPause
    结束后不等回车（脚本化调用时用）。

.EXAMPLE
    .\打包.ps1
    进菜单交互选择。

.EXAMPLE
    .\打包.ps1 -Mode 1
    只打 Addon 包。

.EXAMPLE
    .\打包.ps1 -Mode 5 -Yes -NoPause
    无人值守出完整交付件。

.NOTES
    运行方式：右键「使用 PowerShell 运行」，或在 PowerShell 里 .\打包.ps1。
    机器执行策略拦住时用：
        powershell -NoProfile -ExecutionPolicy Bypass -File .\打包.ps1

    本文件必须保存为「带 BOM 的 UTF-8」。Windows PowerShell 5.1 会把没有 BOM
    的脚本按系统 ANSI 代码页解析，中文会变成乱码并导致语法错误。

    维护提示：LIMS 安装包是按当前 docker-compose.yml 的宿主挂载项【逐项列举】
    拷贝的（nginx/、addons/customers、两个 .sh、三个运行时目录）。compose 里新增
    一处 ./xxx:/yyy 挂载而不同步改 New-LimsPackage，包里就会缺 xxx，现场表现是
    容器起不来或行为不对。模式 3/4 的「全部镜像」清单在主流程的 $allImages。
#>
[CmdletBinding()]
param(
    [ValidateSet('1', '2', '3', '4', '5')]
    [string]$Mode,
    [string]$Version,
    [string]$OutputRoot,
    [switch]$Compress,
    [switch]$SeparateImages,
    [switch]$IncludeDevFiles,
    [switch]$SkipGitPull,
    [switch]$SkipDockerPull,
    [switch]$Yes,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'

# 私有镜像仓库。docker pull 之前要先 docker login，用户名见下面这个常量，
# 密码人工输入（脚本里绝不存密码）。一台机器一般登录一次就一直有效。
$REGISTRY      = 'crpi-z99l88o2fu3lae8l.cn-hangzhou.personal.cr.aliyuncs.com'
$REGISTRY_USER = '厦门南乔'

# 站点 id，取自 docker-compose.yml 里 instance 的 SITE 环境变量，只用来在文档里
# 拼访问地址
$SITE_ID = 'MaiLIMS'

#region ── 公共小工具 ────────────────────────────────────────────────────────
# 这一段和 labgate\打包.ps1 里的同名函数是刻意重复的：两个目录各自是一份独立
# 交付物，谁都能单独拷走用，不为了去重引入跨目录依赖。

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
# 直接抛异常 —— 「镜像不存在」这种预期内的失败会变成脚本崩溃。临时把
# ErrorActionPreference 放成 Continue 才能安静地拿退出码。
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

# 拿 stdout；命令失败返回 $null
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

# git pull。失败不直接终止：本仓库里有些文件是运行时生成的（例如 setupmenu 的
# .mo），工作区长期是脏的，pull 被拒很常见。这时把话说清楚，由人决定要不要用
# 当前工作区继续打包。
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
        Write-Warn2 "当前不在 master 分支，交付件通常应该从 master 打"
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

# 拉镜像。私有仓库先确保登录；公共镜像（postgres / nginx）在国内网络下经常拉不
# 动，本机已有就只警告不终止。
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

# 展开 compose 里的 ${VAR} 与 ${VAR:-默认值}
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
        if ($line -match '^(\s*)build:\s*$')   { $blockIndent = $Matches[1].Length; continue }
        if ($line -match '^(\s*)build:\s+\S')  { continue }   # build: . 这种单行写法
        $out.Add($line)
    }
    return $out.ToArray()
}

# 用 docker compose config 校验产出的 compose 文件。语法错、变量缺失、BOM 之类的
# 问题在这里就暴露，而不是等实施同事在客户现场发现。
function Test-ComposeFile([string]$Directory) {
    Push-Location $Directory
    try {
        & docker compose -f docker-compose.yml config -q
        if ($LASTEXITCODE -ne 0) { throw '包内 docker-compose.yml 校验失败，产物不可用。' }
    } finally {
        Pop-Location
    }
    Write-Ok '包内 docker-compose.yml 校验通过（docker compose config）'
}

# robocopy 拷目录树，顺手剔掉编译产物。robocopy 退出码 0-7 都算成功，>=8 才是错。
function Copy-Tree {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )
    $roboArgs = @($Source, $Destination, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
    if ($ExcludeDirs.Count)  { $roboArgs += @('/XD') + $ExcludeDirs }
    if ($ExcludeFiles.Count) { $roboArgs += @('/XF') + $ExcludeFiles }
    & robocopy @roboArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 拷贝失败（退出码 $LASTEXITCODE）：$Source -> $Destination" }
    $global:LASTEXITCODE = 0
}

# 包内所有文本文件：不带 BOM 的 UTF-8、行尾 LF。
#
#   - 不带 BOM：跟仓库里现有的 .md 一致；BOM 还会让 YAML 解析器直接报
#     「found character that cannot start any token」，也会在 Linux 上 cat 出一个
#     多余字符。（唯一必须带 BOM 的是 .ps1 本身，那是 PS 5.1 的要求。）
#   - LF：包是拿到 Linux 服务器上用的。Win10 1809 以后的记事本也认 LF。
function Write-ConfFile([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, ($Text -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))
}

function Write-DocFile([string]$Path, [string]$Text) {
    Write-ConfFile $Path $Text
}

# shell 脚本：不带 BOM、行尾 LF。BOM 会让 #! 失效（bad interpreter），CRLF 会让
# shebang 变成 /bin/sh\r —— 两种都是容器里立刻报错的经典坑。
function Write-ShFile([string]$Path, [string]$Text) {
    Write-ConfFile $Path $Text
}

# 把已经拷进暂存区的 .sh 全部规范成 LF。仓库有 .gitattributes 保证签出就是 LF，
# 但万一谁的 git 配置把它变成了 CRLF，这里兜住。
function Repair-ShellScript([string]$Directory) {
    foreach ($f in (Get-ChildItem -LiteralPath $Directory -Filter '*.sh' -File -Recurse)) {
        $text = [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($f.FullName))
        if ($text -match "`r`n") {
            Write-ConfFile $f.FullName $text
            Write-Warn2 "$($f.Name) 原来是 CRLF，已改成 LF"
        }
    }
}

# 找一个本机已有的 Linux 镜像，用来在容器里打 tar（见 New-TarGzArchive 的说明）
function Get-TarHelperImage([string[]]$Preferred) {
    foreach ($ref in (@('busybox:latest', 'alpine:latest', 'alpine:3.22') + $Preferred)) {
        if ($ref -and (Test-ImageLocal $ref)) { return $ref }
    }
    return $null
}

# 打 .tar.gz。
#
# 为什么绕道容器：Windows 上的 tar.exe（bsdtar）写出来的归档，文件权限一律
# 0666、目录 0777，没有可执行位。而 docker-compose.yml 把 docker-entrypoint.sh
# 挂进容器当 ENTRYPOINT，Linux 服务器上解包后没有 +x，容器直接起不来
# （permission denied）。在容器里 cp -a 到容器自己的文件系统、chmod、再 tar，
# 权限位才是准的；容器里的 tar 也天然按 UTF-8 存文件名（包里有中文文件名）。
#
# 本机连一个 Linux 镜像都没有时退回 tar.exe，此时权限位不准，靠包里的
# 一键启动.sh 兜底（它先 chmod +x 再 up）。
function New-TarGzArchive {
    param(
        [string]$StagingRoot,
        [string]$Name,
        [string]$OutFile,
        [string[]]$ExecFiles = @(),
        [string[]]$PreferredImages = @()
    )
    $outDir  = Split-Path -Parent $OutFile
    $outName = Split-Path -Leaf $OutFile
    $image   = Get-TarHelperImage $PreferredImages

    if ($image) {
        Write-Note "在容器里打包（$image），以保证 Linux 上的文件权限正确"
        # 一行 sh，不带引号和空格：包目录名是脚本自己生成的纯 ASCII 名字。
        # chmod -R a-x,a+X = 目录给 x、文件去掉 x（从 Windows 挂载进来一律是 0777）
        $cmd = "set -e; cp -a /src/$Name /w/$Name; cd /w; chmod -R a-x,a+X $Name; chmod -R u+rw,go+r,go-w $Name"
        foreach ($f in $ExecFiles) { $cmd += "; [ -f $Name/$f ] && chmod 755 $Name/$f" }
        $cmd += "; tar -czf /out/$outName $Name; tar -tvzf /out/$outName | grep -E 'entrypoint|gen-custom|启动' || true"
        $src = $StagingRoot -replace '\\', '/'
        $dst = $outDir -replace '\\', '/'
        & docker run --rm -v "${src}:/src:ro" -v "${dst}:/out" -w /w $image sh -c $cmd |
            ForEach-Object { Write-Note $_ }
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $OutFile)) { return }
        Write-Warn2 '容器打包失败，退回本机 tar.exe（包内可执行位可能丢失，解包后需 chmod +x *.sh）'
    } else {
        Write-Warn2 '本机没有可用的 Linux 镜像，用 tar.exe 打包（解包后需 chmod +x *.sh，或直接用包里的 一键启动.sh）'
    }

    if (-not (Get-Command tar -ErrorAction SilentlyContinue)) { throw '找不到 tar.exe，无法打 tar.gz。' }
    & tar.exe --options hdrcharset=UTF-8 -czf $OutFile -C $StagingRoot $Name
    if ($LASTEXITCODE -ne 0) {
        & tar.exe -czf $OutFile -C $StagingRoot $Name
        if ($LASTEXITCODE -ne 0) { throw "tar.exe 打包失败（退出码 $LASTEXITCODE）" }
    }
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
        # 空目录没有文件条目，单独补一条目录条目，免得结构缺一块
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
# 不落中间那个大 tar（省一遍磁盘往返）。
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
        $total = 0L
        $mark = 0L
        while (($n = $proc.StandardOutput.BaseStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $gz.Write($buffer, 0, $n)
            $total += $n
            if (($total - $mark) -ge 256MB) {
                $mark = $total
                Write-Host ("`r    已读入 {0} ..." -f (Format-Size $total)) -NoNewline
            }
        }
        $gz.Dispose()
    } finally {
        $fs.Dispose()
    }
    $proc.WaitForExit()
    Write-Host "`r                                        `r" -NoNewline
    if ($proc.ExitCode -ne 0) {
        Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
        throw "docker save 失败：$($stderr.Result)"
    }
}

# 产物旁边放一个 sha256sum 兼容的校验文件（两个空格分隔，Linux 上可 sha256sum -c）
function New-Checksum([string]$FilePath) {
    $hash = (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLower()
    $name = Split-Path -Leaf $FilePath
    # 校验文件本身不能带 BOM，否则 sha256sum -c 读不了第一行
    Write-ConfFile "$FilePath.sha256" "$hash  $name`n"
    return $hash
}

function Get-UniquePath([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $Path }
    $dir  = Split-Path -Parent $Path
    $leaf = Split-Path -Leaf $Path
    # 双后缀（.tar.gz）要整体当扩展名，不能只切最后一个点
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
#endregion

#region ── 版本信息与清单 ───────────────────────────────────────────────────

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

# 扫描 addon 目录，从 setup.py 里读 egg 名和版本号。gen-custom-addon.sh 也是这么
# 认 addon 的：只有「带 setup.py 的一级子目录」才算。
function Get-AddonInventory([string]$CustomersDir) {
    $list = @()
    foreach ($dir in (Get-ChildItem -LiteralPath $CustomersDir -Directory | Sort-Object Name)) {
        $setup = Join-Path $dir.FullName 'setup.py'
        if (-not (Test-Path -LiteralPath $setup)) { continue }
        $text = Get-Content -LiteralPath $setup -Raw -Encoding UTF8
        $egg = $dir.Name
        $ver = '-'
        if ($text -match "(?m)^\s*name\s*=\s*[`"']([^`"']+)[`"']")    { $egg = $Matches[1] }
        if ($text -match "(?m)^\s*version\s*=\s*[`"']([^`"']+)[`"']") { $ver = $Matches[1] }
        $list += [pscustomobject]@{ Dir = $dir.Name; Egg = $egg; Version = $ver }
    }
    return $list
}

function New-VersionFile {
    param(
        [string]$Path,
        [string]$Kind,
        [hashtable]$Extra = @{},
        [object[]]$Addons = @()
    )
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine('MaiLIMS 交付件版本信息')
    [void]$sb.AppendLine('================================================')
    [void]$sb.AppendLine("包类型      : $Kind")
    [void]$sb.AppendLine("版本号      : $script:PkgVersion")
    [void]$sb.AppendLine("打包时间    : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    [void]$sb.AppendLine("打包机器    : $env:COMPUTERNAME / $env:USERNAME")
    [void]$sb.AppendLine("git 提交    : $($script:Git.Commit)  ($($script:Git.Branch))")
    [void]$sb.AppendLine("提交时间    : $($script:Git.Date)")
    [void]$sb.AppendLine("工作区状态  : $($script:Git.Dirty)")
    foreach ($k in $Extra.Keys) {
        [void]$sb.AppendLine(('{0,-12}: {1}' -f $k, $Extra[$k]))
    }
    if ($Addons.Count -gt 0) {
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine("客户 add-on 清单（共 $($Addons.Count) 个）")
        [void]$sb.AppendLine('目录名 / egg 名 / 版本')
        [void]$sb.AppendLine('------------------------------------------------')
        foreach ($a in $Addons) {
            [void]$sb.AppendLine(('{0,-36} {1,-32} {2}' -f $a.Dir, $a.Egg, $a.Version))
        }
    }
    Write-DocFile $Path $sb.ToString()
}
#endregion

#region ── 生成的文档内容 ───────────────────────────────────────────────────
# 模板一律用单引号 here-string：里面有大量 markdown 反引号和 shell 的 $()，
# 用双引号 here-string 会被 PowerShell 当转义符和变量吃掉。变量靠 {{占位符}} 替。

function Get-StartScript {
    $tpl = @'
#!/bin/sh
# MaiLIMS 一键启动（Linux 服务器上执行：sh 一键启动.sh）
#
# 用 sh 调用，不依赖本文件有没有可执行位。它做三件事：
#   1. 给挂进容器的脚本补上可执行位 —— 从 Windows 打的包解出来常常没有 +x，
#      而 docker-compose.yml 把 docker-entrypoint.sh 挂进容器当 ENTRYPOINT，
#      少了 +x 容器就起不来（permission denied）
#   2. docker compose up -d
#   3. 打印访问地址
set -e
cd "$(dirname "$0")"

chmod +x ./docker-entrypoint.sh ./gen-custom-addon.sh 2>/dev/null || true

echo '==> 启动容器'
docker compose up -d

echo ''
echo '==> 当前状态'
docker compose ps

echo ''
echo '首次启动要跑 buildout 并建站，约 3-10 分钟。盯日志：'
echo '    docker compose logs -f instance'
echo ''
echo '看到 Serving on 之后访问： http://<本机IP>/{{SITE}}'
'@
    return (Expand-Template $tpl @{ SITE = $SITE_ID })
}

function Get-LimsReadme([object[]]$Addons) {
    $tpl = @'
# MaiLIMS 安装说明（{{VERSION}}）

本包是**不含镜像**的安装包：把系统跑起来所需的编排文件、nginx 配置与证书、
客户 add-on 都在里面，镜像另外给（配套的镜像包，或从仓库拉）。

打包时间：{{DATE}}　　代码版本：{{COMMIT}}（{{BRANCH}}）

## 包内容

| 路径 | 说明 |
|---|---|
| `docker-compose.yml` | 编排文件，已剥离 build 段（直接用现成镜像，不在现场构建） |
| `docker-entrypoint.sh` | 容器入口脚本，被挂载进容器，**必须有可执行位** |
| `gen-custom-addon.sh` | 每次启动按 addons/customers 的实际内容生成 buildout 配置 |
| `nginx/conf.d/default.conf` | 反向代理配置（80 / 443） |
| `nginx/certificate/` | HTTPS 证书与私钥，**含私钥，注意交付渠道** |
| `addons/customers/` | 客户 add-on，共 {{ADDON_COUNT}} 个，清单见 版本信息.txt |
| `addons/common/` | 刻意留空：通用 add-on 已编进镜像 |
| `data/ blobstorage/ postgres-data/` | 运行时数据目录（空目录占位） |
| `一键启动.sh` | 补可执行位 + docker compose up -d |
| `版本信息.txt` | 版本号、git 提交、add-on 清单 |

## 需要的镜像

| 服务 | 镜像 |
|---|---|
| instance | `{{IMG_INSTANCE}}` |
| nginx | `{{IMG_NGINX}}` |
| postgres | `{{IMG_POSTGRES}}` |

## 前置条件

- Linux 服务器，装好 Docker Engine 与 compose v2（`docker compose version` 有输出）
- 80 / 443 端口空闲
- 磁盘建议 50GB 以上（ZODB、blob、PostgreSQL 数据都落在本目录下）

## 安装步骤

### 1. 解包

    tar -xzf MaiLIMS-{{VERSION}}-*.tar.gz
    cd MaiLIMS-{{VERSION}}-*/

### 2. 准备镜像（二选一）

离线，用配套的镜像包：

    docker load -i MaiLIMS-images-*.tar     # 或 maitux-lims-*.tar
    docker images                            # 核对 tag 与上表一致

在线，从阿里云仓库拉（需先登录，账号问研发）：

    docker login {{REGISTRY}}
    docker compose pull

### 3. 启动

    sh 一键启动.sh

等价于手工执行：

    chmod +x docker-entrypoint.sh gen-custom-addon.sh
    docker compose up -d

> `chmod +x` 这步不能省。docker-compose.yml 把这两个脚本挂进容器，少了可执行位
> 容器会直接 `permission denied` 起不来。

### 4. 等首次初始化

首次启动要跑 buildout 装客户 add-on、再建 SENAITE 站点，**约 3-10 分钟**：

    docker compose logs -f instance

看到 `Serving on http://0.0.0.0:8080` 表示起好了。

### 5. 访问

    http://<服务器IP>/{{SITE}}
    https://<服务器IP>/{{SITE}}

默认管理员 `admin`，密码见 docker-compose.yml 里 instance 的 `PASSWORD`。
**上线前务必改掉它，同时改 postgres 的 `POSTGRES_PASSWORD`。**

## 日常操作

    docker compose ps                    # 看状态
    docker compose logs -f instance      # 看日志
    docker compose restart instance      # 重启应用
    docker compose down                  # 停（数据都在本目录，不会丢）
    docker compose up -d                 # 起

## 升级客户 add-on

用 Addon 安装包（`MaiLIMS-Addons-*.zip`）覆盖本目录下的 `addons/customers`，然后：

    docker compose restart instance
    docker compose logs -f instance

容器每次启动都会按 `addons/customers` 里**实际存在**的 add-on 重新生成 buildout
配置，所以不用手工维护 `custom-addon.cfg`；删掉某个 add-on 目录也不会导致启动失败。

新装的 add-on 还要在站点后台装 profile：站点设置 -> 附加产品
（`prefs_install_products_form`）。

## 常见问题

**容器反复重启，日志里 `exec /docker-entrypoint.sh: permission denied`**
→ 没做 `chmod +x`。执行 `sh 一键启动.sh`，或手工 chmod 后 `docker compose up -d`。

**`exec /docker-entrypoint.sh: no such file or directory`**
→ 脚本被改成了 CRLF 行尾。`sed -i 's/\r$//' docker-entrypoint.sh gen-custom-addon.sh`。

**80 端口被占**
→ 改 docker-compose.yml 里 nginx 的端口映射，例如 `8086:80`。nginx 配置已经处理好
端口映射下的绝对地址生成，改映射不用动 nginx 配置。

**换正式证书**
→ 覆盖 `nginx/certificate/certificate.pem` 与 `certificate.key`，然后
`docker compose restart nginx`。

**时间差 8 小时**
→ compose 里已显式给了 `TZ: Asia/Shanghai`。界面上显示的时间还受 Plone 的
`portal_timezone` 控制（`@@dateandtime-controlpanel`），那个值存在 ZODB 里。

**站点 404**
→ 建站没成功。`docker compose logs instance | grep -i -E 'error|traceback'`，
常见原因是某个 add-on 的 ZCML 报错。
'@
    return (Expand-Template $tpl @{
        VERSION      = $script:PkgVersion
        DATE         = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        COMMIT       = $script:Git.Commit
        BRANCH       = $script:Git.Branch
        ADDON_COUNT  = $Addons.Count
        IMG_INSTANCE = $script:ComposeImages['instance']
        IMG_NGINX    = $script:ComposeImages['nginx']
        IMG_POSTGRES = $script:ComposeImages['postgres']
        REGISTRY     = $REGISTRY
        SITE         = $SITE_ID
    })
}

function Get-AddonReadme([object[]]$Addons) {
    $rows = ($Addons | ForEach-Object { '| `' + $_.Dir + '` | `' + $_.Egg + '` | ' + $_.Version + ' |' }) -join "`r`n"
    $tpl = @'
# 客户 Add-on 覆盖说明（{{VERSION}}）

本包**只含客户 add-on**（`addons/customers` 的内容），不含镜像、不含编排文件，
适用于「系统已经在跑，只更新 add-on 代码」的场景。

打包时间：{{DATE}}　　代码版本：{{COMMIT}}（{{BRANCH}}）

## 操作步骤

1. 解压本包，得到 `customers` 目录。

2. 覆盖生产环境的 `addons/customers`（部署目录 = 放 docker-compose.yml 的那个目录）：

       cd <部署目录>

       # 先备份，出问题好回退
       tar -czf /tmp/customers-backup-$(date +%Y%m%d-%H%M).tar.gz addons/customers

       # 再覆盖
       cp -r /path/to/customers/. addons/customers/

   > `cp -r` 覆盖是**合并**，不会删掉包里没有的旧目录。要求「和本包完全一致」时，
   > 先 `rm -rf addons/customers` 再整目录拷进去。

3. 重启应用容器：

       docker compose restart instance
       docker compose logs -f instance

   容器启动时会按 `addons/customers` 里实际存在的 add-on 重新生成 buildout 配置
   （`custom-addon.cfg`），不需要手工改任何配置文件。

4. **新增**的 add-on 还要在站点后台装 profile：站点设置 -> 附加产品
   （`prefs_install_products_form`）。只是改了已装 add-on 的代码，重启即可，
   不用重装 profile。

## 什么情况下光覆盖 add-on 不够

以下改动必须重新出**镜像**（打包工具的模式 3），光覆盖 customers 不生效：

- 改了 `senaite.core` / `senaite.lims` 等上游包
- 改了 `addons/common` 里的通用 add-on（它们编在镜像里）
- add-on 新引入了第三方 Python 依赖（buildout 在现场装不了）

## 本包含 {{ADDON_COUNT}} 个 add-on

| 目录 | egg 名 | 版本 |
|---|---|---|
{{ROWS}}

注：目录名和 egg 名可以不一致（例如 `maitux.oauth2.0` 的 egg 名是
`maitux.oauth2`），生成 buildout 配置时以 setup.py 里的 `name=` 为准。
'@
    return (Expand-Template $tpl @{
        VERSION     = $script:PkgVersion
        DATE        = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        COMMIT      = $script:Git.Commit
        BRANCH      = $script:Git.Branch
        ADDON_COUNT = $Addons.Count
        ROWS        = $rows
    })
}

function Get-CommonDirNote {
    return @'
这个目录刻意留空。

common（通用）add-on 是在构建镜像时装进镜像里的（镜像内 /opt/addons/common），
docker-compose.yml 并不挂载本目录，所以部署时这里空着是正常的。

要动 common add-on 得重新出镜像，往这里放文件不生效。
'@
}
#endregion

#region ── 各模式的打包实现 ─────────────────────────────────────────────────

# 模式 1：Addon 包。只要 customers 目录，实施同事整目录覆盖生产环境的
# addons\customers。
function New-AddonPackage {
    Write-Step '打 Addon 安装包'

    $name = "MaiLIMS-Addons-$script:PkgVersion-$script:Stamp"
    $stage = Join-Path $script:StagingRoot $name
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null

    Write-Note '拷贝 addons\customers（剔除 pyc / __pycache__ / egg-info / 运行时生成的 cfg）'
    Copy-Tree -Source (Join-Path $script:Root 'addons\customers') `
              -Destination (Join-Path $stage 'customers') `
              -ExcludeDirs $script:ExcludeDirs -ExcludeFiles $script:ExcludeFiles

    $customers = Join-Path $stage 'customers'
    Remove-DevFile $customers

    $addons = Get-AddonInventory $customers
    Write-Ok "共 $($addons.Count) 个 add-on"

    New-VersionFile -Path (Join-Path $stage '版本信息.txt') -Kind 'Addon 安装包（只含 addons/customers）' -Addons $addons
    Write-DocFile (Join-Path $stage 'Addon覆盖说明.md') (Get-AddonReadme $addons)

    $out = Get-UniquePath (Join-Path $script:OutDir "$name.zip")
    Write-Note '压缩成 zip'
    New-ZipArchive $stage $out
    Add-Artifact $out
    Remove-Item -LiteralPath $stage -Recurse -Force
}

function Remove-DevFile([string]$CustomersDir) {
    if ($IncludeDevFiles) { return }
    $removed = 0
    foreach ($f in $script:AddonDevFiles) {
        $p = Join-Path $CustomersDir $f
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force; $removed++ }
    }
    if ($removed) { Write-Note "已剔除 customers 根下 $removed 个开发件（-IncludeDevFiles 可保留）" }
}

# 模式 2：LIMS 安装包。够在「镜像已就位」的机器上 docker compose up -d 起来的全部
# 文件，不含镜像本身。
function New-LimsPackage {
    Write-Step '打 LIMS 安装包（不含镜像）'

    $name = "MaiLIMS-$script:PkgVersion-$script:Stamp"
    $stage = Join-Path $script:StagingRoot $name
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null

    # compose：剥掉 build 段（包里没有 Dockerfile 和源码）
    $lines = Get-Content -LiteralPath (Join-Path $script:Root 'docker-compose.yml') -Encoding UTF8
    Write-ConfFile (Join-Path $stage 'docker-compose.yml') (((Remove-ComposeBuild $lines) -join "`n") + "`n")
    Write-Ok 'docker-compose.yml 已剥离 build 段（改用现成镜像）'

    # .env：这个目录目前没有（compose 里的值是写死的），有就一起带上
    $envFile = Join-Path $script:Root '.env'
    if (Test-Path -LiteralPath $envFile) {
        Copy-Item -LiteralPath $envFile -Destination (Join-Path $stage '.env')
        Write-Ok '.env 已打入包内'
    } else {
        Write-Note '本目录没有 .env（compose 里的配置是写死的），跳过'
    }

    # 挂进容器的两个脚本：必须带、必须 LF、必须可执行
    foreach ($sh in @('docker-entrypoint.sh', 'gen-custom-addon.sh')) {
        Copy-Item -LiteralPath (Join-Path $script:Root $sh) -Destination (Join-Path $stage $sh)
    }
    Repair-ShellScript $stage

    Write-Note '拷贝 nginx（配置 + 证书）'
    Copy-Tree -Source (Join-Path $script:Root 'nginx') -Destination (Join-Path $stage 'nginx')

    Write-Note '拷贝 addons\customers'
    Copy-Tree -Source (Join-Path $script:Root 'addons\customers') `
              -Destination (Join-Path $stage 'addons\customers') `
              -ExcludeDirs $script:ExcludeDirs -ExcludeFiles $script:ExcludeFiles
    $customers = Join-Path $stage 'addons\customers'
    Remove-DevFile $customers

    # common addon 已经编进镜像（Dockerfile 里的 /opt/addons/common），compose 也没
    # 挂它，包里给个空目录只是让结构看起来完整。
    New-Item -ItemType Directory -Force -Path (Join-Path $stage 'addons\common') | Out-Null
    Write-DocFile (Join-Path $stage 'addons\common\说明.txt') (Get-CommonDirNote)

    # compose 里这三个是宿主目录挂载。先建好空目录，省得 docker 自己建出 root
    # 属主的目录。
    foreach ($d in @('data', 'blobstorage', 'postgres-data')) {
        $p = Join-Path $stage $d
        New-Item -ItemType Directory -Force -Path $p | Out-Null
        Write-DocFile (Join-Path $p '.keep') "运行时数据目录，占位用，勿删本目录。`r`n"
    }

    $addons = Get-AddonInventory $customers
    $imageLines = ($script:ComposeImages.Keys | ForEach-Object { "$_ = $($script:ComposeImages[$_])" }) -join '; '
    New-VersionFile -Path (Join-Path $stage '版本信息.txt') `
        -Kind 'LIMS 安装包（不含镜像）' `
        -Extra @{ '所需镜像' = $imageLines } `
        -Addons $addons

    Write-ShFile (Join-Path $stage '一键启动.sh') (Get-StartScript)
    Write-DocFile (Join-Path $stage '安装说明.md') (Get-LimsReadme $addons)

    Test-ComposeFile $stage

    $out = Get-UniquePath (Join-Path $script:OutDir "$name.tar.gz")
    Write-Note '压缩成 tar.gz（保留 LF 与可执行位，目标是 Linux 服务器）'
    New-TarGzArchive -StagingRoot $script:StagingRoot -Name $name -OutFile $out `
        -ExecFiles @('docker-entrypoint.sh', 'gen-custom-addon.sh', '一键启动.sh') `
        -PreferredImages @($script:ComposeImages['nginx'], $script:ComposeImages['postgres'], $script:ComposeImages['instance'])
    Add-Artifact $out
    Remove-Item -LiteralPath $stage -Recurse -Force
}

# 模式 3 / 4：镜像包
function New-ImagePackage {
    param([string[]]$Refs, [string]$BaseName, [string]$Kind)

    Write-Step "导出镜像：$($Refs -join ', ')"

    foreach ($ref in $Refs) { Update-Image $ref }
    foreach ($ref in $Refs) {
        if (-not (Test-ImageLocal $ref)) { throw "本机没有镜像 $ref，无法导出。" }
    }

    # 粗略的空间检查：OCI 归档大小约等于各层压缩态之和，也就是 inspect 的 Size
    $need = 0L
    foreach ($ref in $Refs) { $need += [long](& docker image inspect $ref --format '{{.Size}}') }
    $qualifier = (Split-Path -Qualifier $script:OutDir).TrimEnd(':')
    $drive = Get-PSDrive -Name $qualifier -ErrorAction SilentlyContinue
    if ($drive -and $drive.Free -lt ($need * 1.3)) {
        Write-Warn2 ('输出盘剩余 {0}，本次约需 {1}，可能不够' -f (Format-Size $drive.Free), (Format-Size $need))
        if (-not (Confirm-Continue '继续？')) { throw '已取消。' }
    }

    $ext = if ($Compress) { '.tar.gz' } else { '.tar' }
    $out = Get-UniquePath (Join-Path $script:OutDir "$BaseName$ext")
    Write-Note ('docker save（约 {0}，请耐心等待）' -f (Format-Size $need))
    Export-DockerImage -Refs $Refs -OutFile $out -Gzip:$Compress
    Add-Artifact $out

    # 镜像归档旁边放一份可读清单：装机时要核对 tag 和镜像 ID
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine("MaiLIMS 镜像包 —— $Kind")
    [void]$sb.AppendLine('================================================')
    [void]$sb.AppendLine("归档文件  : $(Split-Path -Leaf $out)")
    [void]$sb.AppendLine("打包时间  : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    [void]$sb.AppendLine("git 提交  : $($script:Git.Commit)  ($($script:Git.Branch))")
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine('镜像清单')
    [void]$sb.AppendLine('------------------------------------------------')
    foreach ($ref in $Refs) {
        $id      = & docker image inspect $ref --format '{{.Id}}'
        $size    = [long](& docker image inspect $ref --format '{{.Size}}')
        $created = & docker image inspect $ref --format '{{.Created}}'
        [void]$sb.AppendLine($ref)
        [void]$sb.AppendLine("    $id")
        [void]$sb.AppendLine(('    {0}   创建于 {1}' -f (Format-Size $size), $created))
    }
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine('导入方法（目标机器上，与归档文件同目录执行）：')
    [void]$sb.AppendLine("    docker load -i $(Split-Path -Leaf $out)")
    [void]$sb.AppendLine('    docker images        # 核对 tag 与上面一致')
    Write-DocFile (Join-Path $script:OutDir ((Split-Path -Leaf $out) + '.清单.txt')) $sb.ToString()
}
#endregion

#region ── 主流程 ───────────────────────────────────────────────────────────

function Show-Banner {
    Write-Host ''
    Write-Host '  ============================================' -ForegroundColor DarkCyan
    Write-Host '   MaiLIMS 打包工具' -ForegroundColor White
    Write-Host "   目录：$script:Root" -ForegroundColor DarkGray
    Write-Host '  ============================================' -ForegroundColor DarkCyan
}

function Show-Menu {
    Write-Host ''
    Write-Host '  请选择打包模式：' -ForegroundColor White
    Write-Host ''
    Write-Host '   1  Addon 安装包        ' -NoNewline -ForegroundColor Yellow
    Write-Host '只含 addons/customers，覆盖生产目录即可'
    Write-Host '   2  LIMS 安装包         ' -NoNewline -ForegroundColor Yellow
    Write-Host 'compose + nginx + addons，不含镜像'
    Write-Host '   3  maitux-lims 镜像    ' -NoNewline -ForegroundColor Yellow
    Write-Host '只导出应用镜像'
    Write-Host '   4  全部镜像            ' -NoNewline -ForegroundColor Yellow
    Write-Host 'lims + nginx + postgres'
    Write-Host '   5  完整交付            ' -NoNewline -ForegroundColor Yellow
    Write-Host '= 2 + 4，新装机器用这个'
    Write-Host ''
    Write-Host '   0  退出' -ForegroundColor DarkGray
    Write-Host ''
    while ($true) {
        $sel = (Read-Host '  输入序号').Trim()
        if ($sel -eq '0' -or $sel -eq 'q') { return $null }
        if ($sel -match '^[1-5]$') { return $sel }
        Write-Host '  无效输入，请输入 0-5' -ForegroundColor Red
    }
}

try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

$script:Root = $PSScriptRoot
if (-not $script:Root) { $script:Root = Split-Path -Parent $MyInvocation.MyCommand.Definition }

$script:ExcludeDirs = @('__pycache__', '.git', '.idea', '.vscode', '.pytest_cache', '.mypy_cache', '.trae', 'node_modules', '*.egg-info')
$script:ExcludeFiles = @('*.pyc', '*.pyo', '*.pyd', '*.orig', '*.rej', '.DS_Store', 'Thumbs.db', 'custom-addon.cfg')
# customers 根目录下的开发件，交付包里默认不带
$script:AddonDevFiles = @(
    'lint_addon.py', 'lint_baseline.json', 'selftest_gate.py', 'selftest_r14.py',
    'Addon摘要.xlsx', 'Git操作速查表.md', 'SENAITE-Addon开发规则.md'
)

$exitCode = 0
try {
    Show-Banner

    $selected = if ($Mode) { $Mode } else { Show-Menu }
    if (-not $selected) { Write-Host ''; Write-Host '  已退出。' -ForegroundColor DarkGray; return }

    Write-Step '环境检查'
    Test-Prerequisite
    Write-Ok "docker $(& docker info --format '{{.ServerVersion}}')，compose $(& docker compose version --short)"

    # 仓库根：git pull 在这里做（本目录是仓库的子目录）
    $script:RepoRoot = Invoke-SilentOut 'git' @('-C', $script:Root, 'rev-parse', '--show-toplevel')
    if (-not $script:RepoRoot) { $script:RepoRoot = Split-Path -Parent $script:Root }

    Write-Step '更新代码（git pull）'
    Update-Repository $script:RepoRoot
    $script:Git = Get-GitInfo $script:RepoRoot

    # 版本号：参数 > VERSION 文件 > 目录名
    $script:PkgVersion = $Version
    if (-not $script:PkgVersion) {
        $vf = Join-Path $script:Root 'VERSION'
        if (Test-Path -LiteralPath $vf) { $script:PkgVersion = (Get-Content -LiteralPath $vf -Raw).Trim() }
    }
    if (-not $script:PkgVersion) { $script:PkgVersion = Split-Path -Leaf $script:Root }
    $script:Stamp = Get-Date -Format 'yyyyMMdd'

    # 镜像引用一律从 compose 里读，不在脚本里另抄一份
    $script:ComposeImages = Get-ComposeImage -ComposePath (Join-Path $script:Root 'docker-compose.yml') `
                                             -EnvMap (Read-DotEnv (Join-Path $script:Root '.env'))
    Write-Note "版本号：$script:PkgVersion"
    foreach ($k in $script:ComposeImages.Keys) { Write-Note "镜像 $k = $($script:ComposeImages[$k])" }

    $script:OutDir = if ($OutputRoot) { $OutputRoot } else { Join-Path $script:Root 'dist' }
    $script:StagingRoot = Join-Path $script:OutDir '.staging'
    New-Item -ItemType Directory -Force -Path $script:StagingRoot | Out-Null

    $imgInstance = $script:ComposeImages['instance']
    $allImages = @($imgInstance, $script:ComposeImages['nginx'], $script:ComposeImages['postgres']) |
        Where-Object { $_ }

    switch ($selected) {
        '1' { New-AddonPackage }
        '2' { New-LimsPackage }
        '3' { New-ImagePackage -Refs @($imgInstance) -BaseName "maitux-lims-$script:PkgVersion-$script:Stamp" -Kind '仅应用镜像' }
        '4' {
            if ($SeparateImages) {
                foreach ($ref in $allImages) {
                    $short = ($ref -split '/')[-1] -replace ':', '-'
                    New-ImagePackage -Refs @($ref) -BaseName "$short-$script:Stamp" -Kind '单个镜像'
                }
            } else {
                New-ImagePackage -Refs $allImages -BaseName "MaiLIMS-images-$script:PkgVersion-$script:Stamp" -Kind '全部镜像（lims + nginx + postgres）'
            }
        }
        '5' {
            New-ImagePackage -Refs $allImages -BaseName "MaiLIMS-images-$script:PkgVersion-$script:Stamp" -Kind '全部镜像（lims + nginx + postgres）'
            New-LimsPackage
        }
    }

    Write-Step '完成'
    Write-Host "    输出目录：$script:OutDir" -ForegroundColor White
    Write-Host ''
    foreach ($a in $script:Artifacts) {
        Write-Host ('    {0,-52} {1,10}' -f $a.Name, (Format-Size $a.Size)) -ForegroundColor Green
        Write-Host ('      sha256 {0}...' -f $a.Sha256.Substring(0, 16)) -ForegroundColor DarkGray
    }
    Write-Host ''
    Write-Note '每个产物旁有同名 .sha256（Linux 上：sha256sum -c 文件名.sha256）'
    Write-Note '交付前请核对 版本信息.txt / 清单.txt 里的版本号与镜像 ID'
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
