import type { ChatMessage } from "../../types";

export default function MessageBubble({
  message,
  children,
}: {
  message: ChatMessage;
  children?: React.ReactNode;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-2.5 ${
          isUser ? "bg-amber/15 text-amber" : "bg-white/5 text-white/90"
        }`}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {children}
      </div>
    </div>
  );
}
