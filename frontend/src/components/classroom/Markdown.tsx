import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { cn } from '../../lib/utils'

/** 兼容 \( ... \) 与 \[ ... \] 写法；跳过围栏代码块。 */
function normalizeMath(input: string): string {
  return input
    .split(/(```[\s\S]*?```)/g)
    .map((chunk, index) =>
      index % 2 === 1
        ? chunk
        : chunk
            .replace(/\\\[/g, '$$')
            .replace(/\\\]/g, '$$')
            .replace(/\\\(/g, '$')
            .replace(/\\\)/g, '$'),
    )
    .join('')
}

export function Markdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn('markdown-body', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: (props) => {
            const { node, ...rest } = props
            void node
            return <a {...rest} target="_blank" rel="noreferrer noopener" />
          },
        }}
      >
        {normalizeMath(content)}
      </ReactMarkdown>
    </div>
  )
}
