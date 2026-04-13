import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import type { Components } from "react-markdown";

const components: Components = {
  h1: ({ children }) => (
    <h1 className="mb-3 mt-6 text-xl font-bold text-foreground first:mt-0">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-5 text-lg font-semibold text-foreground first:mt-0">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-4 text-base font-semibold text-foreground">{children}</h3>
  ),
  p: ({ children }) => (
    <p className="mb-3 text-sm leading-relaxed text-muted-foreground">{children}</p>
  ),
  ul: ({ children }) => <ul className="mb-3 list-disc pl-5 text-sm text-muted-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 list-decimal pl-5 text-sm text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="mb-1">{children}</li>,
  code: ({ className, children, ...props }) => {
    const isBlock = className?.startsWith("language-") || className?.startsWith("hljs");
    if (isBlock) {
      return (
        <code className={`${className ?? ""} block overflow-x-auto rounded bg-card p-3 text-xs`} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className="rounded bg-card px-1.5 py-0.5 font-mono text-xs text-foreground" {...props}>
        {children}
      </code>
    );
  },
  pre: ({ children }) => <pre className="mb-3 overflow-x-auto">{children}</pre>,
  table: ({ children }) => (
    <div className="mb-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b border-border">{children}</thead>,
  th: ({ children }) => (
    <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">{children}</th>
  ),
  td: ({ children }) => <td className="border-b border-border px-3 py-2 text-muted-foreground">{children}</td>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline hover:text-primary/80">
      {children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  blockquote: ({ children }) => (
    <blockquote className="mb-3 border-l-2 border-border pl-4 italic text-muted-foreground">{children}</blockquote>
  ),
  hr: () => <hr className="my-4 border-border" />,
};

interface Props {
  content: string;
  className?: string;
}

export function MarkdownRenderer({ content, className }: Props) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
