import { useEffect, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { createPortal } from 'react-dom'
import { Image } from 'antd'

interface Props {
  src: string
  width?: number
  height?: number
  zoomSize?: number
}

interface ZoomState {
  lensLeft: number
  lensTop: number
  lensSide: number
  panelLeft: number
  panelTop: number
  panelSize: number
  backgroundSizeX: number
  backgroundSizeY: number
  backgroundX: number
  backgroundY: number
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

export default function HoverZoomImage({ src, width = 280, height = 280, zoomSize = 480 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null)
  const [zoom, setZoom] = useState<ZoomState | null>(null)

  useEffect(() => {
    setNatural(null)
    setZoom(null)
  }, [src])

  useEffect(() => {
    const hide = () => setZoom(null)
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    return () => {
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('resize', hide)
    }
  }, [])

  const handleMove = (event: ReactMouseEvent<HTMLDivElement>) => {
    const container = containerRef.current
    if (!container || !natural) return
    const rect = container.getBoundingClientRect()
    const scale = Math.min(width / natural.width, height / natural.height)
    const displayWidth = natural.width * scale
    const displayHeight = natural.height * scale
    const offsetX = (width - displayWidth) / 2
    const offsetY = (height - displayHeight) / 2

    const x = event.clientX - rect.left - offsetX
    const y = event.clientY - rect.top - offsetY
    if (x < 0 || y < 0 || x > displayWidth || y > displayHeight) {
      setZoom(null)
      return
    }

    const padding = 12
    const gap = 12
    const lensSide = Math.min(160, displayWidth, displayHeight)
    const lensX = clamp(x - lensSide / 2, 0, displayWidth - lensSide)
    const lensY = clamp(y - lensSide / 2, 0, displayHeight - lensSide)

    const panelSize = Math.max(
      200,
      Math.min(zoomSize, window.innerWidth - padding * 2, window.innerHeight - padding * 2),
    )
    let panelLeft = rect.right + gap
    if (panelLeft + panelSize > window.innerWidth - padding) {
      panelLeft = rect.left - panelSize - gap
    }
    panelLeft = Math.max(padding, panelLeft)
    const panelTop = clamp(
      rect.top,
      padding,
      Math.max(padding, window.innerHeight - panelSize - padding),
    )

    const zoomRatio = panelSize / lensSide
    setZoom({
      lensLeft: offsetX + lensX,
      lensTop: offsetY + lensY,
      lensSide,
      panelLeft,
      panelTop,
      panelSize,
      backgroundSizeX: displayWidth * zoomRatio,
      backgroundSizeY: displayHeight * zoomRatio,
      backgroundX: -lensX * zoomRatio,
      backgroundY: -lensY * zoomRatio,
    })
  }

  return (
    <div
      ref={containerRef}
      style={{ position: 'relative', display: 'inline-block', width, height, borderRadius: 6, background: '#fff', lineHeight: 0 }}
      onMouseEnter={handleMove}
      onMouseMove={handleMove}
      onMouseLeave={() => setZoom(null)}
    >
      <Image
        src={src}
        alt="商品图片"
        width={width}
        height={height}
        style={{ objectFit: 'contain', borderRadius: 6, cursor: 'zoom-in' }}
        preview={{ mask: false }}
        onLoad={event => {
          const image = event.currentTarget
          if (image.naturalWidth && image.naturalHeight) {
            setNatural({ width: image.naturalWidth, height: image.naturalHeight })
          }
        }}
      />
      {zoom && (
        <div
          style={{
            position: 'absolute',
            left: zoom.lensLeft,
            top: zoom.lensTop,
            width: zoom.lensSide,
            height: zoom.lensSide,
            border: '1px solid rgba(0, 0, 0, 0.35)',
            background: 'rgba(255, 255, 255, 0.25)',
            boxShadow: 'inset 0 0 0 1px rgba(255, 255, 255, 0.7)',
            pointerEvents: 'none',
            zIndex: 2,
          }}
        />
      )}
      {zoom && createPortal(
        <div
          style={{
            position: 'fixed',
            left: zoom.panelLeft,
            top: zoom.panelTop,
            width: zoom.panelSize,
            height: zoom.panelSize,
            zIndex: 1050,
            pointerEvents: 'none',
            backgroundImage: `url("${src}")`,
            backgroundRepeat: 'no-repeat',
            backgroundSize: `${zoom.backgroundSizeX}px ${zoom.backgroundSizeY}px`,
            backgroundPosition: `${zoom.backgroundX}px ${zoom.backgroundY}px`,
            backgroundColor: '#fff',
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            boxShadow: '0 12px 32px rgba(0, 0, 0, 0.18)',
          }}
        />,
        document.body,
      )}
    </div>
  )
}
