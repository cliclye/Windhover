import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cleanChatText } from "../chatText";

export function MarkdownBody({ text }: { text: string }) {
  const cleaned = cleanChatText(text);
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        ),
        pre: ({ children }) => <pre className="md-pre">{children}</pre>,
        code: ({ className, children, ...props }) => {
          const inline = !className;
          return inline ? (
            <code className="md-inline-code" {...props}>
              {children}
            </code>
          ) : (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
      }}
    >
      {cleaned}
    </ReactMarkdown>
  );
}
