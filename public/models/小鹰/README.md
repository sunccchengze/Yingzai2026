# 小鹰 · 3D 模型（Blender）

英仔爱心社吉祥物 **小鹰** 的高精度 `.blend` 模型。

造型对齐官方 2D（`public/images/小鹰/`）：奶油白头、巧克力棕身、金黄喙爪、大圆眼、头顶小撮毛、展开的分层飞羽。质感走 **绒羽/幼鸟绒毛**（粒子毛发 + Sheen + 次表面散射），不是硬表面卡通。

## 文件

| 文件 | 说明 |
| --- | --- |
| `小鹰.blend` | Blender 4.2 工程（推荐 4.2 LTS 或更新） |
| `preview/xiaoying_hero.png` | Cycles 预览 |
| `../../../../scripts/build_xiaoying.py` | 可重复生成的建模脚本 |

## 打开后怎么看

1. 用 **Blender 4.2+** 打开 `小鹰.blend`。
2. 渲染引擎切到 **Cycles**（毛发在 EEVEE 里会变细/变假）。
3. 已准备四台相机：`Camera_Hero` / `Camera_Front` / `Camera_Side` / `Camera_ThreeQuarter`。
4. 角色根物体是 `XiaoYing_Root`，旋转它即可改飞行姿态。

## 把毛发开到「超密」

预览为了内存做了克制。你本机显存/内存够的话，选中 `Head` / `Body`，粒子系统里把：

- **Rendered** 子毛发（`rendered_child_count`）加到 `40–80`
- **Number** 父毛发适量增加

即可得到更密的绒感。

## 重新生成

```bash
python scripts/build_xiaoying.py --no-render
```

需要本机已安装 Blender 的 `bpy` 模块，或直接在 Blender 里 `Scripting` 运行该脚本。

## 配色（从「小鹰飞行.png」取样）

- 头：`#FCF5EC`
- 身体：`#6B4A2D`
- 翅膀：`#4E341E` 一带
- 喙 / 爪：`#F9B32C`
- 眼睛：近黑 `#120A04`
