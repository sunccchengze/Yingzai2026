# 小鹰 3D 重建 · 进度留档（识图 Agent 交接）

> 上游交接文件：`交接给识图Agent_开场白.md`（提交 `a638d45`）
> 本文件是**执行侧留档**：记录已完成的工作、可复现的环境、以及下一棒该从哪继续。
> 当前进度：**约 50%**（工具链就绪、几何可生成；尚未完成渲染校准迭代）。

---

## 一、任务定义（来自开场白，摘要）

照 `public/images/小鹰/{小鹰正面,小鹰侧面,小鹰背面}.png` 三张官方 2D 图，
做一版**正/侧/背都高度贴合**的 `.blend`。要求：

1. 先把整体轮廓/胖瘦/比例彻底拿准，再抠羽毛细节；
2. 正面、侧面、背面都要像；
3. 交付 `.blend`（可附预览渲染图）；
4. 渲完自己对照参考图**校准迭代**，不许一次交差就完。

---

## 二、参考图量化结果（已完成，不需重做）

不靠肉眼估比例，全部从像素测得。测量脚本即 `scripts/3d/xiaoying_refs.py`。

### 2.1 画布与关键分界

| 视图 | 尺寸 | 头部 | 身体 | 备注 |
| --- | --- | --- | --- | --- |
| 正面 | 410×610 | y 6–366 | y 325–568 | 最宽 409px @ y435；头占全高约 55% |
| 侧面 | 396×600 | y 6–355 | y 316–555 | 喙尖伸到 x=0；尾羽尖 x≈395 @ y450 |
| 背面 | 395×614 | y 5–366 | y 327–576 | 白后脑下缘为波浪状绒毛边 |

### 2.2 配色（像素采样中位数）

| 部位 | 色值 |
| --- | --- |
| 头 / 颈 奶油白 | `#FCF8F2` |
| 身体 巧克力棕 | `#6E4D2E` |
| 翅膀 / 尾羽（暗一档） | `#57381F` |
| 喙 / 脚爪 金黄 | `#F6B32A` |
| 口腔 / 舌 | `#E25C48` |
| 眼 / 描边 近黑 | `#281C0C` |

> 注意：开场白里给的是粗略值（如身体 `#604818`）；本表是**实测中位数**，以本表为准。

### 2.3 特征位置（正面图像素坐标）

- 双眼：中心 y≈212，左眼 cx≈132、右眼 cx≈281，**眼距 149–155px**，眼球直径约 68px
- 喙：y 215–333，最宽 x 137–270；口腔红色块 x179–230 / y287–320
- 双爪：y 551–607，左爪 x91–182、右爪 x228–319
- 头冠小撮毛：正面 y0–60 附近，尖端 x≈238–246

---

## 三、建模方法论（关键设计，务必延续）

**核心思想：数据驱动，而非手调参数。**

前一棒（无视觉能力）用像素 IoU 盲调，交付不被认可。本棒改为：

```
正面图逐行 → 该行的 X 半宽 ax、X 中心 cx
侧面图对应行 → 该行的 Y 半深 ay、Y 中心 cy
        ↓
     椭圆截面环 (cx, cy, ax, ay, z)
        ↓
      沿 Z 轴 loft 成实体
```

于是**渲染出的正面/侧面剪影与参考图天然对齐**，不需要反复试错猜比例。
三视图之间的行号用包围盒按比例映射（`Refs.side_row / back_row`），
解决三张图总高不一致（610 / 600 / 614）的问题。

坐标约定（Blender 右手系，Z 朝上）：

- `X` 左右，正 X = 小鹰自己的左手边（观众右侧）
- `Y` 前后，**负 Y = 面朝方向（喙）**，正 Y = 尾巴
- `Z` 上下，`Z=0` 为脚底；全高归一化到 **2.0 单位**

---

## 四、已交付的工具链（已推上 main）

位于 `scripts/3d/`：

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `xiaoying_refs.py` | 197 | 从三视图提取逐行轮廓 + 配色常量 + 像素↔世界坐标映射。**不依赖 bpy**，可单独运行做数据体检 |
| `build_xiaoying_v2.py` | 798 | 主建模：头 / 绒毛边 / 冠羽 / 身 / 翅 / 喙 / 眼 / 脚 / 尾 分件 loft + Freestyle 描边（还原 2D 黑边）+ 正侧背三相机 + 三点光 |
| `calibrate.py` | 113 | 校准器：渲染剪影（film_transparent 的 alpha）与参考图按包围盒归一后算 **IoU**，输出红绿叠图（红=缺肉 / 绿=多肉 / 灰=重合） |
| `blenv.sh` | ~120 | 无头环境自愈（见下节） |

### 运行方式

```bash
source scripts/3d/blenv.sh
python3 scripts/3d/xiaoying_refs.py                     # 数据体检
python3 scripts/3d/build_xiaoying_v2.py --out /tmp/build/小鹰.blend --no-render
python3 scripts/3d/build_xiaoying_v2.py --out /tmp/build/小鹰.blend --samples 24
python3 scripts/3d/calibrate.py --preview /tmp/build/preview
```

### 当前实测

- 建模耗时 **约 2 秒**（`--no-render`）
- 生成包围盒：`x -0.652..0.652   y -0.816..0.574   z 0.035..2.005`
  （高 2.0 单位、喙尖 y=−0.816、尾 y=+0.574，比例合理）

---

## 五、⚠️ 环境自愈：沙箱里怎么跑起 Blender（踩坑记录）

沙箱**没有 Blender，且 apt 源不可达**。解法与两个大坑：

### 坑 1：`inspect.py` 劫持标准库（已修复）

仓库原有 `scripts/3d/inspect.py`，与 Python 标准库 `inspect` 同名。
只要 cwd 或 sys.path 命中该目录，**numpy 都会导入失败**（numpy 内部 `import inspect`）。

→ 已重命名为 `inspect_scene.py`，旧文件删除。**不要再起名 `inspect.py`。**

### 坑 2：pip 版 bpy 缺 X11/GL 运行时

`pip install bpy==4.2.0` 可装上，但 `import bpy` 报缺 `libXrender.so.1` 等 8 个库。
真 X11 在沙箱装不上；而**离屏渲染根本不调这些符号**，只是链接期形式依赖。

→ `blenv.sh` 自动生成**同名同符号的空桩库**到 `~/.blstub`：

1. 用 `nm -D --undefined-only` 递归扫描 bpy 包内所有 `.so`
2. 正则挑出 `gl* / X* / _X* / xkb_* / SmcC* / IceC*` 共 **165 个**未定义符号
3. 全部生成空函数，编成 8 个桩库（`libGL.so.1` / `libXrender.so.1` / …）
4. `export LD_LIBRARY_PATH`

注意：**空 .so 不够**——`libusd_ms.so` 会逐个解析 `glXMakeCurrent`、`glFinish`、
`XFixesShowCursor`、`_XiGetDevicePresenceNotifyEvent` 等具体符号，必须补齐符号本体。

该脚本是**幂等自愈**的：沙箱快照回滚清掉 `~/.blstub` 后，重新 `source` 会自动重建。
实测从零重建到 `import bpy` 成功，耗时 < 2 秒。

### 依赖清单

```bash
pip install --break-system-packages bpy==4.2.0 numpy pillow scipy
```

> 沙箱回滚也会清掉 pip 包，`blenv.sh` 会检测并打印补装命令。

---

## 六、下一棒待办（剩余 50%）

1. **渲染三视图** —— `--samples 24`，Cycles CPU 2 核，预计 10–20 分钟。
   相机 `Camera_Front / Camera_Side / Camera_Back` 已配置，`film_transparent=True`
   便于取 alpha 做剪影。
2. **IoU 校准迭代** —— 跑 `calibrate.py`，看红绿叠图判断哪里胖了/瘦了，
   回改 `build_xiaoying_v2.py` 里对应部件的剖面采样区间，反复迭代。
   建议目标：三视图 IoU 均 **≥ 0.90**。
3. **细节层** —— 轮廓达标后再做羽毛/绒毛（`xiaoying_feathers.py` 可复用）。
4. **交付** —— `.blend` + 三视图预览图放进 `小鹰3D模型/`，更新横向比较 README，
   然后按铁律推送。

---

## 七、推送铁律（来自开场白，必须遵守）

```bash
git status --short
git fetch origin main
git merge-base --is-ancestor origin/main HEAD && echo "FF 安全" || echo "先 rebase"
git push origin arena/01a08633-yingzai2026            # 先推自己分支
git push origin arena/01a08633-yingzai2026:main       # 快进推送到 main
```

- **禁止** `gh pr merge` / `gh pr close` —— 会导致 Arena 关闭会话远程通道，未推送提交永久丢失。
- 每完成一单元立刻 commit + push，绝不攒提交。
- 绝不 `-f` 强推 main。

### 本棒踩到的 git 状况（供参考）

沙箱回滚导致本地提交丢失、且工作区残留了 `~$*.xlsx`（Excel 锁文件）和对
`2026英仔爱心社报名表 的副本.xlsx` 的意外二进制改动。
处理：`git checkout --` 还原 xlsx、删除锁文件，再 `git rebase origin/main`；
其中 `fc68b1d` 因已包含在远端 main 中而 `git rebase --skip`。

**建议**：把 `~$*` 加进 `.gitignore`，避免 Excel 临时文件混入提交。
