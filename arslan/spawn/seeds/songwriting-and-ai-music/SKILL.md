---
name: songwriting-and-ai-music
description: 词曲创作 + AI 音乐提示 —— 主题→hook→结构(verse/pre/chorus/bridge)的写词纪律,押韵与节拍自查,另附 Suno 风格 style prompt 块;交付歌词与提示词,不是音频。
version: 0.1.0
authors:
  - Arslan
---

## Trigger

当用户要「写歌 / 歌词 / 给 Suno(或同类 AI 音乐工具)写提示词 / 把一段文字改成歌」时激活。产出物是两块文本:结构完整的歌词(带 [Verse]/[Chorus] 等段落标签)+ 独立的 style prompt 块;你不能生成或播放音频,这一点从一开始就说清楚。

## 决策规则

- **先定主题一句话,再找 hook**:动笔前把整首歌浓缩成一句话主题(它想让听者带走什么感受);hook 是主题的最口语、最上口的表达——先写出 3-5 个候选 hook 挑一个,再围绕它展开,没有 hook 的歌只是分行的散文。
- **结构服务情绪弧线**:默认 Verse 1 → Pre-Chorus → Chorus → Verse 2 → Pre → Chorus → Bridge → Final Chorus;verse 讲具体场景推进叙事,pre-chorus 抬升张力,chorus 承载 hook 且每次重复词面基本一致,bridge 换视角或转折——一处结构偏离默认就要有理由。
- **意象压倒抽象**:"心碎了"是抽象,"你留下的杯子我一直没洗"是意象;每段 verse 至少两个可看见/听见/摸到的具体细节;抽象总结词(爱、痛、自由)只允许出现在 chorus,且要被 verse 的意象挣得。
- **押韵与节拍自查**:定好韵式(如 verse 用 ABAB、chorus 用 AABB)后逐行标注检查;每行朗读数出重音拍数,同段落各行拍数一致或有意呼应;为凑韵而硬拗的词一律换掉——宁可近韵(slant rhyme)自然,不要完美韵生硬。中文注意声调顺口,英文注意重音落在实词上。
- **style prompt 独立成块**:歌词之外单独给一个 style prompt 块,内容包括:genre(可复合,如 "indie folk with electronic textures")、tempo/BPM(具体数字,如 "slow ballad, 72 BPM")、mood(2-3 个形容词)、vocals(性别/质感/和声,如 "female airy vocals, layered harmonies")、instrumentation(3-5 件主奏乐器)。风格描述不写进歌词正文。
- **段落标签用工具约定格式**:歌词内用方括号结构标签——[Intro]、[Verse 1]、[Pre-Chorus]、[Chorus]、[Bridge]、[Outro],需要时加演绎提示如 [Instrumental Break]、[Whispered];标签用英文(工具识别更稳),歌词语言随用户。
- **交付诚实**:明说你交付的是歌词 + 提示词文本,不是音频;AI 音乐工具对提示的执行有随机性,建议用户同一提示生成多版挑选;不承诺"听起来会像某某歌手"。
- **迭代按维度收反馈**:用户说"不太对"时,引导拆维度——是主题跑偏、hook 不上口、意象太淡、还是风格块不对味;一次只改一个维度并说明改了什么,不整首推倒重来。
