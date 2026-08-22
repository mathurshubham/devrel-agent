"use client";

import * as React from "react";

/**
 * MarkdownLite — a deliberately small, dependency-free renderer for the
 * Analyst pipeline's Intel Brief markdown (exec summary, clusters, a stance
 * table, quotes, content gaps, recommended actions). It is not a general
 * markdown engine: it covers exactly what the brief template produces
 * (headings, bold/italic/inline code, bullet & numbered lists, blockquotes,
 * pipe tables, horizontal rules, and plain paragraphs) and falls back to
 * pre-wrapped plain text for anything else, rather than pulling in a
 * markdown dependency for a single internal document type.
 */

function renderInline(text: string): React.ReactNode[] {
    const nodes: React.ReactNode[] = [];
    // Order matters: inline code first (so ** inside `code` isn't touched),
    // then bold, then italic.
    const tokenRe = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    let key = 0;

    while ((match = tokenRe.exec(text)) !== null) {
        if (match.index > lastIndex) {
            nodes.push(text.slice(lastIndex, match.index));
        }
        const token = match[0];
        if (token.startsWith("`")) {
            nodes.push(
                <code key={key++} className="rounded bg-muted px-1 py-0.5 text-[0.85em] font-mono">
                    {token.slice(1, -1)}
                </code>
            );
        } else if (token.startsWith("**")) {
            nodes.push(<strong key={key++} className="font-semibold text-foreground">{token.slice(2, -2)}</strong>);
        } else {
            nodes.push(<em key={key++}>{token.slice(1, -1)}</em>);
        }
        lastIndex = match.index + token.length;
    }
    if (lastIndex < text.length) {
        nodes.push(text.slice(lastIndex));
    }
    return nodes;
}

function isTableSeparator(line: string): boolean {
    return /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/.test(line.trim());
}

function splitTableRow(line: string): string[] {
    let trimmed = line.trim();
    if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
    if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
    return trimmed.split("|").map((cell) => cell.trim());
}

export function MarkdownLite({ content, className }: { content: string; className?: string }) {
    const blocks = React.useMemo(() => parse(content), [content]);
    return <div className={className}>{blocks}</div>;
}

function parse(content: string): React.ReactNode[] {
    const lines = content.replace(/\r\n/g, "\n").split("\n");
    const out: React.ReactNode[] = [];
    let i = 0;
    let key = 0;

    while (i < lines.length) {
        const line = lines[i];

        if (line.trim() === "") {
            i++;
            continue;
        }

        // Horizontal rule
        if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
            out.push(<hr key={key++} className="my-4 border-border/40" />);
            i++;
            continue;
        }

        // Headings
        const headingMatch = /^(#{1,4})\s+(.*)$/.exec(line);
        if (headingMatch) {
            const level = headingMatch[1].length;
            const text = headingMatch[2];
            const sizeClass =
                level === 1
                    ? "text-xl font-semibold mt-6 mb-2"
                    : level === 2
                        ? "text-lg font-semibold mt-5 mb-2"
                        : level === 3
                            ? "text-base font-semibold mt-4 mb-1.5"
                            : "text-sm font-semibold uppercase tracking-wide text-muted-foreground mt-3 mb-1";
            const tagName = `h${Math.min(level, 6)}`;
            out.push(
                React.createElement(tagName, { key: key++, className: sizeClass }, renderInline(text))
            );
            i++;
            continue;
        }

        // Pipe table: a row followed by a separator row
        if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
            const header = splitTableRow(line);
            i += 2;
            const rows: string[][] = [];
            while (i < lines.length && lines[i].trim() !== "" && lines[i].includes("|")) {
                rows.push(splitTableRow(lines[i]));
                i++;
            }
            out.push(
                <div key={key++} className="my-3 overflow-x-auto rounded-md border border-border/40">
                    <table className="w-full text-sm">
                        <thead className="bg-muted/40">
                            <tr>
                                {header.map((h, idx) => (
                                    <th key={idx} className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                        {renderInline(h)}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row, rIdx) => (
                                <tr key={rIdx} className="border-t border-border/30">
                                    {row.map((cell, cIdx) => (
                                        <td key={cIdx} className="px-3 py-2 align-top">
                                            {renderInline(cell)}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            );
            continue;
        }

        // Blockquote
        if (/^>\s?/.test(line)) {
            const quoteLines: string[] = [];
            while (i < lines.length && /^>\s?/.test(lines[i])) {
                quoteLines.push(lines[i].replace(/^>\s?/, ""));
                i++;
            }
            out.push(
                <blockquote key={key++} className="my-3 border-l-2 border-primary/40 pl-3 text-muted-foreground italic">
                    {quoteLines.map((l, idx) => (
                        <p key={idx} className="my-0.5">{renderInline(l)}</p>
                    ))}
                </blockquote>
            );
            continue;
        }

        // Unordered list
        if (/^\s*[-*]\s+/.test(line)) {
            const items: string[] = [];
            while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
                items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
                i++;
            }
            out.push(
                <ul key={key++} className="my-2 list-disc space-y-1 pl-5 text-sm">
                    {items.map((item, idx) => (
                        <li key={idx}>{renderInline(item)}</li>
                    ))}
                </ul>
            );
            continue;
        }

        // Ordered list
        if (/^\s*\d+[.)]\s+/.test(line)) {
            const items: string[] = [];
            while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
                items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
                i++;
            }
            out.push(
                <ol key={key++} className="my-2 list-decimal space-y-1 pl-5 text-sm">
                    {items.map((item, idx) => (
                        <li key={idx}>{renderInline(item)}</li>
                    ))}
                </ol>
            );
            continue;
        }

        // Paragraph: gather consecutive plain lines
        const paraLines: string[] = [];
        while (
            i < lines.length &&
            lines[i].trim() !== "" &&
            !/^(#{1,4})\s+/.test(lines[i]) &&
            !/^\s*[-*]\s+/.test(lines[i]) &&
            !/^\s*\d+[.)]\s+/.test(lines[i]) &&
            !/^>\s?/.test(lines[i]) &&
            !/^(-{3,}|\*{3,}|_{3,})$/.test(lines[i].trim())
        ) {
            paraLines.push(lines[i]);
            i++;
        }
        out.push(
            <p key={key++} className="my-2 text-sm leading-relaxed">
                {renderInline(paraLines.join(" "))}
            </p>
        );
    }

    return out;
}
