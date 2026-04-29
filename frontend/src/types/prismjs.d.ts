declare module "prismjs" {
  export type PrismGrammar = Record<string, unknown>;

  export interface PrismStatic {
    languages: Record<string, PrismGrammar | undefined>;
    highlight(code: string, grammar: PrismGrammar, language: string): string;
  }

  const Prism: PrismStatic;
  export default Prism;
}
