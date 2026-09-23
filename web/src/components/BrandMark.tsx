import type { ImgHTMLAttributes } from 'react';
import { useIconStore } from '../stores/iconStore';

/** One brand source for sidebar, settings and every assistant message. */
export default function BrandMark({ className = '', alt = 'Arslan', ...props }: ImgHTMLAttributes<HTMLImageElement>) {
  const style = useIconStore(s => s.style);
  return <img {...props} src={style === 'monochrome' ? '/brand/mark-monochrome.svg?v=20260923' : '/arslan-mark.png?v=20260923'}
    alt={alt} draggable={false} className={`arslan-brand arslan-brand--${style} shrink-0 object-contain ${className}`} />;
}
