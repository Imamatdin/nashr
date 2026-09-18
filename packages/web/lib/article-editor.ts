import type { ArticleBlock, ArticleBlockType, ArticleContent } from "./api";

export function newBlock(
  type: ArticleBlockType,
  id = crypto.randomUUID(),
): ArticleBlock {
  return {
    id,
    type,
    text: "",
    level: type === "heading" ? 2 : null,
    citations: [],
  };
}

export function addBlock(
  content: ArticleContent,
  afterId: string | null,
  type: ArticleBlockType,
  id?: string,
): ArticleContent {
  const block = newBlock(type, id);
  const index =
    afterId === null
      ? content.blocks.length - 1
      : content.blocks.findIndex((item) => item.id === afterId);
  const at = Math.max(0, index + 1);
  return {
    ...content,
    blocks: [
      ...content.blocks.slice(0, at),
      block,
      ...content.blocks.slice(at),
    ],
  };
}

export function removeBlock(
  content: ArticleContent,
  id: string,
): ArticleContent {
  if (content.blocks.length <= 1) return content;
  return {
    ...content,
    blocks: content.blocks.filter((block) => block.id !== id),
  };
}

export function moveBlock(
  content: ArticleContent,
  id: string,
  delta: -1 | 1,
): ArticleContent {
  const index = content.blocks.findIndex((block) => block.id === id);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= content.blocks.length)
    return content;
  const blocks = [...content.blocks];
  [blocks[index], blocks[target]] = [blocks[target], blocks[index]];
  return { ...content, blocks };
}

export function wordCount(content: ArticleContent): number {
  return content.blocks.reduce((count, block) => {
    const words = block.text.trim().split(/\s+/u).filter(Boolean);
    return count + words.length;
  }, 0);
}
