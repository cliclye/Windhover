import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cleanChatText } from "../chatText";
import { renderMathAndHeadings } from "../mathText";
import { useSmoothText } from "../smooth";
import { linkCitations, type WebSource } from "../webSearch";

export function MarkdownBody({
  text,
  streaming = false,
  sources,
}: {
  text: string;
  streaming?: boolean;
  /** Web sources for this reply: [1]-style citations become links. */
  sources?: WebSource[];
}) {
  const shown = useSmoothText(text, streaming);
  let cleaned = linkCitations(renderMathAndHeadings(cleanChatText(shown)), sources);
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
        a: ({ href, children }) => {
          const cite = typeof children === "string" && /^\d{1,2}$/.test(children) && sources?.length;
          return (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className={cite ? "cite" : undefined}
              title={cite ? sources.find((s) => String(s.n) === children)?.title : undefined}
            >
              {children}
            </a>
          );
        },
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
