# Git 操作速查表（本项目专用）

适用仓库：`senaite.docker`

适用场景：日常开发、同步上游、提交客户 addon 变更、创建 PR 前自检。

## 一、先记住这几个项目约束

- `origin` 是公司 Fork：`NingboMaiTux/senaite.docker`
- `upstream` 是上游官方：`senaite/senaite.docker`
- `custom-addon.cfg` 是运行时自动生成文件，**不要提交**
- `.mo` 是容器自动编译产物，**不要提交**
- 本地为了调试改过的 `docker-compose.yml`、环境配置等，提交前先确认是不是本次任务真正要交付的内容
- 新增客户 addon 时，目录里必须有 `setup.py`，否则容器启动时会被 `gen-custom-addon.sh` 跳过

## 二、最常用的 8 条命令

### 1. 看当前改了什么

```powershell
git status
git diff
```

### 2. 只暂存本次任务相关文件

```powershell
git add "addons/customers/某个插件/README.md"
git add "addons/customers/某个插件/src/xxx.py"
```

不要上来就 `git add .`

### 3. 提交

```powershell
git commit -m "fix: 修复某某问题"
```

### 4. 推送当前分支到公司 Fork

```powershell
git push -u origin HEAD
```

### 5. 拉上游最新 `master`

```powershell
git fetch upstream
git checkout master
git pull upstream master
```

### 6. 基于最新 `master` 切新分支

```powershell
git checkout master
git pull upstream master
git checkout -b "你的分支名"
```

### 7. 查看当前远端配置

```powershell
git remote -v
```

### 8. 看最近几次提交

```powershell
git log --oneline -5
```

## 三、这个项目最稳的日常流程

### 场景 A：开始一个新任务

```powershell
git fetch upstream
git checkout master
git pull upstream master
git checkout -b "feature/你的任务名"
```

### 场景 B：开发中提交一次

```powershell
git status
git diff
git add "具体文件1"
git add "具体文件2"
git commit -m "feat: 说明这次改动的目的"
```

### 场景 C：推送并准备提 PR

```powershell
git push -u origin HEAD
```

PR 目标分支一般是公司 Fork 的 `master`，不是 `upstream`。

## 四、提交前必做检查

```powershell
git status
git diff --cached
```

重点看这几类文件有没有误带进去：

- `custom-addon.cfg`
- `*.mo`
- 纯本地调试改动
- 与本任务无关的 `docker-compose.yml`
- 临时脚本，如 `_verify*.py`、`_cham*.py`、`tmp_*.py`

如果 `.mo` 被容器自动改了，先还原：

```powershell
git restore "*.mo"
```

如果只是某个文件不想提交，先取消暂存：

```powershell
git restore --staged "文件路径"
```

如果工作区改动也想一起丢掉，再执行：

```powershell
git restore "文件路径"
```

## 五、同步上游时推荐做法

先确认工作区干净，或者先提交 / stash。

```powershell
git fetch upstream
git checkout master
git pull upstream master
git checkout 你的开发分支
git merge master
```

这个仓库里，日常同步更推荐 `merge master`，简单直接，出问题也更容易看懂。

## 六、遇到冲突时

先看哪些文件冲突了：

```powershell
git status
```

处理完冲突文件后：

```powershell
git add "冲突文件路径"
git commit -m "merge: resolve conflicts with master"
```

如果冲突里混着你本地调试配置，先停一下，确认哪些应该保留、哪些只是本地环境差异。

## 七、这个项目里很实用的命令组合

### 只看某个 addon 的改动

```powershell
git diff -- "addons/customers/maitux.hazardcategories"
```

### 看某个文件是谁改的

```powershell
git log -- "addons/customers/SENAITE-Addon开发规则.md"
```

### 看某行是谁最后改的

```powershell
git blame "addons/customers/SENAITE-Addon开发规则.md"
```

## 八、不建议直接这么做

- 不建议 `git add .`
- 不建议把 `.mo` 提交进去
- 不建议手工维护 `custom-addon.cfg`
- 不建议在没看清改动时直接提交 `docker-compose.yml`
- 不建议用破坏性命令清空工作区，除非你非常确定

## 九、提交信息可直接套用

```text
feat: 新增某功能
fix: 修复某个问题
refactor: 重构某段逻辑
docs: 更新项目文档
test: 补充或调整测试
chore: 清理非业务性内容
```

更贴这个项目的写法示例：

```text
fix: 清理 hazard categories 遗留 controlpanel 入口
feat: add setup metadata for INNOCARE.LabelAndReport
docs: update SENAITE addon development rules
```
