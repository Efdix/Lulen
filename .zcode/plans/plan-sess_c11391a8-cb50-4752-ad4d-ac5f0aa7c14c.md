# 计划:自研快速启动器 "Lulen"(Python + PySide6)

## 安装边界(按你的要求,硬性约束)
- **只在 Lulen conda 环境内用 pip 安装包**(如 PySide6),不安装任何系统级软件,不运行任何 GUI 安装程序;不装 git、不装 VS Code 之类的东西。
- **git 本机已验证可用**(git 2.52.0.windows.1),直接拿来提交,不做任何安装/升级。
- 打包成 exe 一类的事情默认不做;将来若需要,也只考虑纯 pip 可装进环境的工具(如 PyInstaller),仍不碰手动安装器。
- 全程使用的解释器:`D:\Science\miniforge\envs\Lulen\python.exe`(本机 PATH 上的 python 是微软商店空壳,不使用)。

## 背景与已确认信息
- 目标:仿 Rolan 5 的紧凑悬浮启动面板,自用免费;对标开源项目 Maye(MIT,已停更,github.com/25H/Maya)的功能清单,并逐步超越。
- 技术栈:Python + PySide6;界面为仿 Rolan 紧凑面板(无边框悬浮网格 + 右键编辑,无独立管理主窗口)。
- 环境:conda 为 Miniforge3(`D:\Science\miniforge`,不在 PATH,用全路径调用);尚无 Lulen 环境,需新建。工作区 `D:\System\Documents\GitHub\Lulen` 为空目录。
- 功能范围(你选定):热键悬浮面板、拖拽添加条目、分组/多页、自启与外观;后续持续迭代。

## 第 0 步:环境搭建(仅 conda 环境内操作)
1. `D:\Science\miniforge\Scripts\conda.exe create -n Lulen python=3.12 -y`
2. `D:\Science\miniforge\envs\Lulen\python.exe -m pip install PySide6`(网络慢则加清华镜像)
3. 依赖**只有 PySide6**;其余全部标准库:ctypes(全局热键 RegisterHotKey)、winreg(开机自启)、json、shutil、urllib 等,不引 pywin32。

## 项目结构(D:\System\Documents\GitHub\Lulen)
```
main.py                  # 入口:单实例(QLocalServer)、装配、启动面板
lulen/
  config.py              # 数据模型 Item/Group/Settings + JSON 原子写盘 + 自动备份
  hotkey.py              # ctypes RegisterHotKey + QAbstractNativeEventFilter(WM_HOTKEY)
  launch.py              # 启动逻辑:exe(带参数/工作目录)/文件/文件夹/网址/命令
  icons.py               # 图标提取(QFileIconProvider)+ 网址 favicon 后台抓取 + 缓存
  panel.py               # 无边框悬浮面板:置顶、拖拽移动、失焦隐藏、滚轮翻页
  item_card.py           # 单条目控件:图标+名称、单击启动、拖入拖出
  groups.py              # 分组/多页:页签条、跨组拖拽、组管理
  settings_dialog.py     # 设置窗口:热键录制、主题、列数/图标大小、自启开关
  tray.py                # 托盘图标与菜单(显示/隐藏、设置、退出)
  theme.py               # 深/浅主题 QSS + 强调色
  autostart.py           # HKCU\...\CurrentVersion\Run 写/删注册表自启
assets/  requirements.txt  README.md  .gitignore
```
数据文件:`%APPDATA%\Lulen\config.json`(原子写入:临时文件+replace;另存 config.bak.json 防损坏)。

## 实施里程碑(每步完成即运行验证 + git 提交,用现有 git,不装新东西)
**M1 面板骨架**:无边框置顶工具窗(不占任务栏/Alt-Tab)、默认热键 Ctrl+Shift+Z 呼出/隐藏(被占用时自动回落并提示,运行时会检测与 Rolan 的冲突)、失焦/ESC 自动隐藏、托盘图标(左键切换、右键菜单)、单实例(二次启动唤出面板而非开新进程)、窗口位置记忆。

**M2 条目与启动**:JSON 数据模型与自动多列网格;从资源管理器拖入 exe/文件/多文件/文件夹/网址添加;右键菜单:打开/编辑(名称、目标、参数、工作目录、自定义图标)/在所在位置显示/删除;图标自动提取;拖拽排序;点击启动(launch.py 分类型分发)。

**M3 分组/多页**:分组页签(新建/重命名/删除/排序)、每组独立网格、滚轮和按钮翻页、跨分组拖拽移动条目。

**M4 设置与外观**:设置窗口(热键录制、深/浅/跟随系统主题、强调色、列数与图标大小、失焦隐藏开关、开机自启开关)、QSS 主题、高 DPI 适配、空态引导文案。

**M5 收尾**:README(用法+热键表)、.gitignore、自启辅助脚本(生成 .vbs 无窗口启动,纯文本文件,不涉及安装)、全面冒烟测试(重启后配置持久化、崩溃安全写盘)。

**M6+ 对标并超越 Maye 的迭代池**(按优先级逐个做,做完 M5 自动继续):条目独立快捷键(快捷键运行项目)、面板显示后直接输入的命令条(`>` 终端、`<` 运行、`s/bd/b/g/d` 搜索引擎前缀)、.lnk/.url 文件解析、`%mp%` 路径变量、网址 favicon 自动获取、配置导入导出备份、中文/拼音过滤搜索、主题皮肤自定义。

## 验证方式
- 每个里程碑:用 `D:\Science\miniforge\envs\Lulen\python.exe main.py` 实际运行冒烟(热键、拖拽、重启持久化),并渲染截图核对界面;git 按里程碑提交。
- 已知风险:全局热键与 Rolan 冲突(已计划自动回落);无 Python on PATH(全程用环境全路径)。

## 需要的执行权限
创建 conda 环境与在环境内 pip 安装;运行/测试该 Python 程序;在工作区用**已有 git** 初始化仓库并提交。