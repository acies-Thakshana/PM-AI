import { useRef, useState } from "react";

export interface ChatAttachment {
  id: string;
  label: string;
  accept: string;
  /** The file already attached for this kind, if any. */
  fileName?: string;
}

interface ChatComposerProps {
  /** Kinds of file that can be attached from the paperclip menu. */
  attachments?: ChatAttachment[];
  onAttach?: (id: string, file: File) => void;
  onDetach?: (id: string) => void;
  placeholder: string;
  /** Called with the trimmed text when the PM sends. */
  onSend: (text: string) => void;
  disabled?: boolean;
  label?: string;
}

/** The rounded message box at the bottom of a conversation. Enter sends, Shift+Enter starts a new line. */
export default function ChatComposer({ placeholder, onSend, disabled = false, label = "Message", attachments = [], onAttach, onDetach }: ChatComposerProps) {
  const [draft, setDraft] = useState("");
  const [menu, setMenu] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pickRef = useRef<ChatAttachment | null>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);

  const send = () => {
    const text = draft.trim();
    if (!text || disabled) return;
    setDraft("");
    if (boxRef.current) boxRef.current.style.height = "auto";
    onSend(text);
  };

  const attached = attachments.filter((a) => a.fileName);

  return (
    <div className="chat-composer-wrap">
      {attached.length > 0 && (
        <div className="chat-composer__files">
          {attached.map((a) => (
            <span key={a.id} className="chat-composer__file">
              {a.label}: {a.fileName}
              <button type="button" aria-label={`Remove ${a.label}`} onClick={() => onDetach?.(a.id)}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        ref={fileRef}
        type="file"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file && pickRef.current) onAttach?.(pickRef.current.id, file);
          e.target.value = "";
        }}
      />
    <form
      className="chat-composer"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      {attachments.length > 0 && (
        <div className="chat-composer__attach">
          <button type="button" className="chat-composer__clip" aria-label="Attach a profile" aria-expanded={menu} disabled={disabled} onClick={() => setMenu((v) => !v)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 11.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l9-9a3.3 3.3 0 0 1 4.7 4.7l-9 9a1.7 1.7 0 0 1-2.4-2.4l8.3-8.3" />
            </svg>
          </button>
          {menu && (
            <div className="chat-composer__menu" role="menu">
              {attachments.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    pickRef.current = a;
                    if (fileRef.current) {
                      fileRef.current.accept = a.accept;
                      fileRef.current.click();
                    }
                    setMenu(false);
                  }}
                >
                  {a.label}
                  <small>{a.fileName ?? "Optional"}</small>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      <textarea
        ref={boxRef}
        rows={1}
        value={draft}
        placeholder={placeholder}
        aria-label={label}
        disabled={disabled}
        onChange={(e) => {
          setDraft(e.target.value);
          e.target.style.height = "auto";
          e.target.style.height = `${e.target.scrollHeight}px`;
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
      />
      <button type="submit" className="chat-composer__send" disabled={!draft.trim() || disabled} aria-label="Send">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
      </button>
    </form>
    </div>
  );
}
