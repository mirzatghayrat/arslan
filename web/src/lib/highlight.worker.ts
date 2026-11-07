import { tokenize } from './highlightTokens';

self.onmessage = ({ data }: MessageEvent<{ code: string; lang: string }>) => {
  self.postMessage(tokenize(data.code, data.lang));
};
