import { Hand, ListChecks, LockKeyhole, Code2 } from "lucide-react";
import { AskCard, Button, CodeBox, ConfirmSheet, Dialog, Notice, ProposalRow, Tag } from "../../components/kit";

/**
 * Dev-only gallery of the surface kit (0.1.55), sample content (kept under __tests__/: sample copy, never shipped),
 * for screenshots in both themes:
 * `npm run dev`, then /#kit-gallery (add `&dark` for the dark theme, `&p=ember` for a palette).
 * Not reachable in a production build (main.tsx gates it on import.meta.env.DEV).
 */
export default function KitGallery() {
  const noop = () => {};
  const icon = "h-[15px] w-[15px] shrink-0";
  return (
    <div className="min-h-screen bg-background p-8 font-sans text-foreground">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(480px,1fr))] items-start gap-10">
        <AskCard keys={false} who="后台作业在问你" title="让 Arslan 在「备忘录」里点击和输入"
          expiresAt={Date.now() + 252_000} totalMs={300_000} queue={{ index: 0, total: 3, onNext: noop }}
          detail={<CodeBox numbered={false} code={"第一步　点击「New Note」\n之后　在新笔记里写标题和正文"} />}
          context={[
            { icon: <ListChecks className={icon} />, text: "来自「在备忘录里新建一条笔记」" },
            { icon: <Hand className={icon} />, text: "这项作业里只问这一次 · 在后台做，不占用你的鼠标键盘" },
            { icon: <LockKeyhole className={icon} />, text: "删除、发送、付款类按钮仍会单独再问 · 从不输入密码" },
          ]}
          onAllow={noop} onDecline={noop} onOpenContext={noop} />
        <AskCard keys={false} who="Arslan 在问你" title="运行一段 AppleScript，整理「备忘录」" said="清理测试留下的笔记"
          risk="这段脚本会删除东西（第 2 行：delete）· 以代码为准" expiresAt={Date.now() + 298_000} totalMs={300_000}
          detail={<CodeBox marks={["delete"]} code={'tell application "Notes"\n  delete (notes whose name = "Hands 冒烟")\nend tell'} />}
          context={[{ icon: <Code2 className={icon} />, text: "每段脚本都会单独问 · 这段只用一次" }]}
          allowLabel="运行一次" onAllow={noop} onDecline={noop} onOpenContext={noop} />
        <div className="flex flex-col gap-4">
          <Notice tone="error" title="模型出错了" action={<Button size="sm" tone="secondary">打开模型设置</Button>}>
            DeepSeek 返回 402：余额不足。换一个模型，或去充值后重试。</Notice>
          <Notice tone="warn" title="需要你看一眼">作业停在「回读核对」：笔记标题和要求不一致。</Notice>
          <Notice tone="info" title="这个模型不支持工具">用它聊天没问题，但 Arslan 不能替你动手。</Notice>
          <div className="overflow-hidden rounded-xl border border-border bg-surface">
            <ProposalRow waiting text="体检报告里的血压数据" meta={<><Tag>关于你</Tag><Tag tone="danger">敏感</Tag>10月6日 的对话里提到</>}
              actions={<><Button size="sm" tone="primary">留下，只给本机用</Button><Button size="sm">不要</Button></>} />
            <ProposalRow text="改名、移动文件 → 用命令行，不去访达里点" meta={<Tag>绕过一次失败</Tag>}
              actions={<span className="text-[12px] text-subtle-foreground">用了 3 次 · 3 次做成</span>} />
          </div>
          <div className="inline-flex h-11 w-fit items-center gap-3.5 rounded-full bg-toast pl-4 pr-2 text-[13px] text-toast-foreground shadow-kit">
            已删除这条做法<button type="button" className="h-[30px] rounded-full bg-toast-foreground/15 px-3 font-semibold">撤销</button>
          </div>
        </div>
      </div>
      <ConfirmSheet open options={{ title: "删除这个模型配置？", action: "删除",
        body: "「DeepSeek · deepseek-v4-flash」和它保存的 API key 会一起删掉，不能撤销。用它的角色会改用你的主模型。" }}
        onAnswer={noop} />
      {location.hash.includes("dialog") && (
        <Dialog open title="项目和记忆" onClose={noop}
          footer={<><Button>取消</Button><Button tone="primary">保存</Button></>}>
          <div className="px-5 py-4 text-[14px]">这个对话属于「Arslan 开发」</div>
        </Dialog>
      )}
    </div>
  );
}
