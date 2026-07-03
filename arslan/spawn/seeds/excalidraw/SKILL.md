---
name: excalidraw
description: Excalidraw 手绘风图表 —— 先网格布局再生成 scene JSON,箭头绑定 source/target,交付可导入 excalidraw.com 的源文件而非"已画好的图"。
version: 0.1.0
authors:
  - Arslan
---

## Trigger

当用户要「手绘风格的图 / excalidraw 图 / 白板草图感的架构图、流程图、示意图」时激活。产出物是一份 Excalidraw scene JSON(`type: "excalidraw"` 顶层对象 + `elements` 数组),用户把它导入 excalidraw.com 或保存为 `.excalidraw` 文件即可打开编辑。若用户只要一张普通静态图而非可编辑白板,考虑 infographic/architecture-diagram 类技能更合适。

## 决策规则

- **先在纸上排版,再写 JSON**:动手生成 elements 之前,先用文字列出布局计划——有哪些节点、分几行几列、每个节点的网格坐标(如 20px 网格,列宽 260、行高 160)。直接边写 JSON 边想坐标必然重叠错位。
- **统一间距与尺寸**:同类节点用同一 width/height(如矩形 200×80),水平/垂直间距全图一致;所有 x/y 落在网格倍数上。整齐的骨架配手绘的线条,才是 Excalidraw 的味道;骨架也乱就只是乱。
- **手绘感靠属性不靠随机坐标**:`roughness: 1`(或 2)、`strokeWidth: 1-2`、`fillStyle: "hachure"` 营造手绘质感;坐标本身保持精确对齐,不要人为抖动位置。
- **箭头必须绑定端点**:每条 arrow 用 `startBinding`/`endBinding` 指向源/目标元素的 `id`(相应元素的 `boundElements` 里登记回来),而不是裸坐标画线——绑定后用户拖动节点箭头会跟随,这是可编辑交付的关键。
- **文字用 label 或 bound text**:节点内文字用容器元素的绑定文本(text element + `containerId`),独立说明才用自由 text;字号全图 2-3 档(标题/节点/注释),中文文本注意给容器留足宽度(约每字 18-20px)。
- **颜色角色化**:strokeColor/backgroundColor 全图固定语义——如主流程一色、外部依赖一色、警示一色,取 Excalidraw 默认调色板(#1e1e1e、#e64980、#1971c2、#2f9e44 等),最多 3-4 种,不为装饰配色。
- **必需字段一个不缺**:每个 element 至少含 `id`(全图唯一字符串)、`type`、`x`、`y`、`width`、`height`、`strokeColor`、`backgroundColor`、`seed`(任意整数);顶层含 `type: "excalidraw"`、`version`、`elements`、`appState`。字段缺失导入时静默丢元素,比语法错误更难排查。
- **渲染契约诚实**:你交付的是 JSON 源文件,不是渲染好的图片——绝不说"我画好了/如图所示";明确告诉用户"导入 excalidraw.com 查看",并说明坐标是按网格规划的、未经视觉验证,导入后如有重叠可直接拖动微调。
- **复杂度守门**:一张图超过 ~30 个元素就先问是否拆分或简化;元素越多,纯靠推理保证不重叠的把握越低,宁可两张清晰的图也不要一张挤爆的图。
