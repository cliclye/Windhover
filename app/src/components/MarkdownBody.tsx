import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cleanChatText } from "../chatText";
import { renderMathAndHeadings } from "../mathText";
import { useSmoothText } from "../smooth";

export function MarkdownBody({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const shown = useSmoothText(text, streaming);
  let cleaned = renderMathAndHeadings(cleanChatText(shown));
  if (streaming && (cleaned.match(/```/g) || []).length % 2 === 0) {
    // hide an opening ** / __ whose closing half hasn't streamed in yet
    cleaned = cleaned.replace(/(\*\*|__)(?![\s\S]*\1)(?=\S)/, (m, mark, offset: number) =>
      (cleaned.slice(0, offset).split(mark).length - 1) % 2 === 0 ? "" : m
    );
  }
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
