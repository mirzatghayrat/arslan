---
name: pretext
description: 文字动效排版 —— 以文字为唯一视觉材料的单文件 HTML 动效(kinetic typography),inline CSS @keyframes + transform,编排节奏与错峰,零库零图片。
version: 0.1.0
authors:
  - Arslan
---

## Trigger

当用户要「文字动效 / kinetic typography / 动态排版 / 把一句话/标语做成动画」时激活。产出物是一个自包含的单文件 `.html`:只用文字 + inline CSS 动画(@keyframes、transform、opacity),不用任何 JS 库、图片或外部字体,双击打开即播放。

## 决策规则

- **文字是唯一材料**:所有视觉效果都从排版本身来——字号对比、字重、字距、颜色、位移、旋转、缩放;不加图形装饰、不加图标、不加背景图。约束就是风格。
- **逐字/逐词拆 span 再编排**:把要动画的文本按词(或按字)包进 `<span>`,每个 span 是一个可独立编排的演员;用 `animation-delay` 做错峰(stagger),典型步长 60-120ms——整句一起动是 PPT,错峰入场才是 choreography。
- **只动 transform 和 opacity**:动画属性限定 `transform`(translate/scale/rotate)与 `opacity`,不动 width/height/top/left/font-size——既是性能纪律(不触发 layout),也逼着你用位移和缩放讲故事。
- **节奏先于样式**:先用文字写出时间轴脚本(0s 主词砸入 → 0.4s 副句逐词淡入 → 2s 强调词放大变色 → 停留 → 循环或定格),再翻译成 @keyframes;easing 有语义——入场用 `cubic-bezier` 的 ease-out(快到慢,有落地感),强调用 overshoot(超过再回弹),匀速 linear 几乎总是错的。
- **可读性红线**:任何一段文字静止可读的时间 ≥ 其字数 × 0.3s;动画过程中文字不可读没关系,但每个语义单元必须有"定格窗口";正文永远不加剧烈持续晃动。看不清的动效再炫也是失败。
- **层级三档制**:主词(最大、最重、最先/最抢眼的动画)、支撑句(中档、跟随入场)、点缀信息(小号、弱动画或不动);全片字号档位 ≤ 3,颜色 ≤ 3(底色 + 主文字色 + 一个强调色),用 CSS 变量定义在 `:root`。
- **系统字体栈**:`font-family` 用系统栈(`-apple-system, 'PingFang SC', 'Noto Sans SC', sans-serif` 兜底中文),不引 webfont——外部字体请求既破坏自包含又造成首帧闪动。
- **循环要有呼吸**:整体循环用最外层容器的 `animation-iteration-count: infinite` 控制,循环点前留 0.5-1s 的静止定格再重来;若内容是"讲完一遍"型,末态定格(`animation-fill-mode: forwards`)优于生硬循环。
- **交付契约**:整份交付就是一个 `.html` 文件内容,`<style>` 内联在文件里;告诉用户保存为 .html 双击打开即可播放;你无法预览它,时间参数是按脚本推算的,用户若觉得某处太快/太慢,报出是哪个词,改对应 delay/duration 即可。
