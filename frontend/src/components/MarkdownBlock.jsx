import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { narrativeEmphasisClass } from "../narrativeRollUi";

const QUOTE_PAIRS = new Map([
  ['"', '"'],
  ["'", "'"],
  ["“", "”"],
  ["‘", "’"],
  ["「", "」"],
  ["『", "』"],
  ["《", "》"],
  ["〈", "〉"],
]);

function findClosingQuote(text, openingIndex, openingQuote, closingQuote) {
  for (let index = openingIndex + 1; index < text.length; index += 1) {
    if (text[index] !== closingQuote || text[index - 1] === "\\") continue;
    // 英文缩写中的撇号不是引语边界；中文直引号不受这一限制。
    if (openingQuote === "'" && /[A-Za-z0-9]/.test(text[index + 1] || "")) continue;
    return index;
  }
  return -1;
}

function highlightQuotedText(text) {
  const source = String(text || "");
  const parts = [];
  let plainStart = 0;

  for (let index = 0; index < source.length; index += 1) {
    const openingQuote = source[index];
    const closingQuote = QUOTE_PAIRS.get(openingQuote);
    if (!closingQuote) continue;
    if (openingQuote === "'" && /[A-Za-z0-9]/.test(source[index - 1] || "")) continue;

    const closingIndex = findClosingQuote(source, index, openingQuote, closingQuote);
    if (closingIndex <= index + 1) continue;
    if (plainStart < index) parts.push(source.slice(plainStart, index));
    parts.push(
      <span className="quoted-phrase" key={`quote-${index}`}>
        {source.slice(index, closingIndex + 1)}
      </span>,
    );
    index = closingIndex;
    plainStart = closingIndex + 1;
  }

  if (plainStart < source.length) parts.push(source.slice(plainStart));
  return parts.length ? parts : source;
}

function highlightQuotedChildren(children) {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") return highlightQuotedText(child);
    if (!React.isValidElement(child) || child.type === "code" || child.type === "pre") return child;
    return React.cloneElement(child, {
      children: highlightQuotedChildren(child.props.children),
    });
  });
}

const HIGHLIGHTED_MARKDOWN_COMPONENTS = {
  p: ({ children }) => <p>{highlightQuotedChildren(children)}</p>,
  li: ({ children }) => <li>{highlightQuotedChildren(children)}</li>,
  blockquote: ({ children }) => <blockquote>{highlightQuotedChildren(children)}</blockquote>,
  h1: ({ children }) => <h1>{highlightQuotedChildren(children)}</h1>,
  h2: ({ children }) => <h2>{highlightQuotedChildren(children)}</h2>,
  h3: ({ children }) => <h3>{highlightQuotedChildren(children)}</h3>,
  h4: ({ children }) => <h4>{highlightQuotedChildren(children)}</h4>,
  h5: ({ children }) => <h5>{highlightQuotedChildren(children)}</h5>,
  h6: ({ children }) => <h6>{highlightQuotedChildren(children)}</h6>,
  th: ({ children }) => <th>{highlightQuotedChildren(children)}</th>,
  td: ({ children }) => <td>{highlightQuotedChildren(children)}</td>,
};

function markdownInlineText(children) {
  return React.Children.toArray(children)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number") return String(child);
      if (React.isValidElement(child)) return markdownInlineText(child.props.children);
      return "";
    })
    .join("");
}

const NARRATIVE_MARKDOWN_COMPONENTS = {
  ...HIGHLIGHTED_MARKDOWN_COMPONENTS,
  em: ({ children }) => {
    const className = narrativeEmphasisClass("em", markdownInlineText(children));
    return <em className={className || undefined}>{children}</em>;
  },
  strong: ({ children }) => {
    const className = narrativeEmphasisClass("strong", markdownInlineText(children));
    return <strong className={className || undefined}>{children}</strong>;
  },
};

export default function MarkdownBlock({ children, highlightQuotes = false, highlightNarrativeRolls = false }) {
  const components = highlightNarrativeRolls
    ? NARRATIVE_MARKDOWN_COMPONENTS
    : highlightQuotes
      ? HIGHLIGHTED_MARKDOWN_COMPONENTS
      : undefined;
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {String(children || "")}
    </ReactMarkdown>
  );
}
