import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Image } from 'antd'

interface Props {
  src: string
  width?: number
  height?: number
  zoomSize?: number
}

export default function HoverZoomImage({ src, width = 280, height = 280, zoomSize = 560 }: Props) {
  const anchorRef = useRef<HTMLDivElement>(null)
  const [hovered, setHovered] = useState(false)
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null)

  useEffect(() => {
    if (!hovered) {
      setPosition(null)
      return
    }
    const update = () => {
      const rect = anchorRef.current?.getBoundingClientRect()
      if (!rect) return
      const gap = 12
      const padding = 12
      let left = rect.right + gap
      if (left + zoomSize > window.innerWidth - padding) {
        left = rect.left - zoomSize - gap
      }
      left = Math.max(padding, left)
      const maxTop = Math.max(padding, window.innerHeight - zoomSize - padding)
      const top = Math.min(
        Math.max(padding, rect.top + rect.height / 2 - zoomSize / 2),
        maxTop,
      )
      setPosition({ left, top })
    }
    update()
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [hovered, zoomSize])

  return (
    <>
      <div
        ref={anchorRef}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{ display: 'inline-block', borderRadius: 6, background: '#fff' }}
      >
        <Image
          src={src}
          alt="商品图片"
          width={width}
          height={height}
          style={{ objectFit: 'contain', borderRadius: 6, cursor: 'zoom-in' }}
          preview={{ mask: '点击放大查看' }}
        />
      </div>
      {hovered && position && createPortal(
        <div
          style={{
            position: 'fixed',
            left: position.left,
            top: position.top,
            width: zoomSize,
            height: zoomSize,
            zIndex: 1050,
            pointerEvents: 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 8,
            background: '#fff',
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            boxShadow: '0 12px 32px rgba(0, 0, 0, 0.18)',
          }}
        >
          <img
            src={src}
            alt="商品大图"
            style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
          />
        </div>,
        document.body,
      )}
    </>
  )
}
