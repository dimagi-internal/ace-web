import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

type Variant = "document" | "chat";

function buildComponents(variant: Variant): Components {
  const inChat = variant === "chat";
  const paraColor = inChat ? "" : "text-muted-foreground";
  const listColor = inChat ? "" : "text-muted-foreground";
  const cellColor = inChat ? "" : "text-muted-foreground";
  const quoteColor = inChat ? "" : "text-muted-foreground";
  const bottomMb = inChat ? "mb-2 last:mb-0" : "mb-3";
  const headingTop = inChat ? "mt-3 first:mt-0" : "mt-6 first:mt-0";

  return {
    h1: ({ children }) => (
      <h1 className={`mb-3 ${headingTop} text-xl font-bold text-foreground`}>{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className={`mb-2 ${headingTop} text-lg font-semibold text-foreground`}>{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className="mb-2 mt-4 text-base font-semibold text-foreground first:mt-0">{children}</h3>
    ),
    p: ({ children }) => (
      <p className={`${bottomMb} text-sm leading-relaxed ${paraColor}`}>{children}</p>
    ),
    ul: ({ children }) => (
      <ul className={`${bottomMb} list-disc pl-5 text-sm ${listColor}`}>{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className={`${bottomMb} list-decimal pl-5 text-sm ${listColor}`}>{children}</ol>
    ),
    li: ({ children }) => <li className="mb-1">{children}</li>,
    code: ({ className, children, ...props }) => {
      const isBlock = className?.startsWith("language-") || className?.startsWith("hljs");
      if (isBlock) {
        return (
          <code
            className={`${className ?? ""} block overflow-x-auto rounded bg-card p-3 text-xs text-foreground`}
            {...props}
          >
            {children}
          </code>
        );
      }
      return (
        <code
          className="rounded bg-card px-1.5 py-0.5 font-mono text-xs text-foreground"
          {...props}
        >
          {children}
        </code>
      );
    },
    pre: ({ children }) => <pre className={`${bottomMb} overflow-x-auto`}>{children}</pre>,
    table: ({ children }) => (
      <div className={`${bottomMb} overflow-x-auto`}>
        <table className="w-full border-collapse text-sm">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="border-b border-border">{children}</thead>,
    th: ({ children }) => (
      <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className={`border-b border-border px-3 py-2 ${cellColor}`}>{children}</td>
    ),
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary underline hover:text-primary/80"
      >
        {children}
      </a>
    ),
    strong: ({ children }) => (
      <strong className="font-semibold text-foreground">{children}</strong>
    ),
    blockquote: ({ children }) => (
      <blockquote className={`${bottomMb} border-l-2 border-border pl-4 italic ${quoteColor}`}>
        {children}
      </blockquote>
    ),
    hr: () => <hr className="my-4 border-border" />,
  };
}

const documentComponents = buildComponents("document");
const chatComponents = buildComponents("chat");

interface Props {
  content: string;
  className?: string;
  variant?: Variant;
}

export function MarkdownRenderer({ content, className, variant = "document" }: Props) {
  const components = variant === "chat" ? chatComponents : documentComponents;
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
