import type { ReactNode } from "react";
import "./ChatMessage.css";

interface ChatMessageProps {
  children: ReactNode;
  /** The PM's own message: a soft bubble on the right, with no avatar. */
  from?: "assistant" | "user";
}

/** One turn of the conversation. Rich content (forms, cards, tables) goes inside the assistant's body. */
export default function ChatMessage({ children, from = "assistant" }: ChatMessageProps) {
  if (from === "user") {
    return (
      <div className="chat-msg chat-msg--user">
        <div className="chat-msg__bubble">{children}</div>
      </div>
    );
  }
  return (
    <div className="chat-msg">
      <div className="chat-msg__avatar" aria-hidden="true">
        AI
      </div>
      <div className="chat-msg__body">{children}</div>
    </div>
  );
}
