import { useEffect, useRef } from 'react'

const CUBE_EDGES = [
  [[-1, -1, -1], [1, -1, -1]], [[-1, 1, -1], [1, 1, -1]],
  [[-1, -1, 1], [1, -1, 1]], [[-1, 1, 1], [1, 1, 1]],
  [[-1, -1, -1], [-1, 1, -1]], [[1, -1, -1], [1, 1, -1]],
  [[-1, -1, 1], [-1, 1, 1]], [[1, -1, 1], [1, 1, 1]],
  [[-1, -1, -1], [-1, -1, 1]], [[1, -1, -1], [1, -1, 1]],
  [[-1, 1, -1], [-1, 1, 1]], [[1, 1, -1], [1, 1, 1]],
]

export default function Map3D({ notes, hovered, onHover }) {
  const canvasRef = useRef(null)
  const stateRef = useRef({ rx: -0.35, ry: 0.6, dragging: false, lastX: 0, lastY: 0, projected: [] })
  const notesRef = useRef(notes)
  notesRef.current = notes
  const hoveredRef = useRef(hovered)
  hoveredRef.current = hovered

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    const css = getComputedStyle(document.documentElement)
    const colors = {
      dot: css.getPropertyValue('--accent').trim(),
      edge: css.getPropertyValue('--border').trim(),
    }
    let raf

    function draw() {
      const st = stateRef.current
      const dpr = window.devicePixelRatio || 1
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (canvas.width !== Math.round(w * dpr)) {
        canvas.width = Math.round(w * dpr)
        canvas.height = Math.round(h * dpr)
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      if (!st.dragging) st.ry += 0.003

      const project = ([x, y, z]) => {
        const cy = Math.cos(st.ry)
        const sy = Math.sin(st.ry)
        const x1 = x * cy + z * sy
        const z1 = -x * sy + z * cy
        const cx = Math.cos(st.rx)
        const sx = Math.sin(st.rx)
        const y1 = y * cx - z1 * sx
        const z2 = y * sx + z1 * cx
        const scale = 2.8 / (2.8 - z2)
        const r = Math.min(w, h) * 0.27
        return { x: w / 2 + x1 * scale * r, y: h / 2 - y1 * scale * r, depth: z2, scale }
      }

      ctx.strokeStyle = colors.edge
      ctx.lineWidth = 1
      ctx.globalAlpha = 0.55
      for (const [a, b] of CUBE_EDGES) {
        const p1 = project(a)
        const p2 = project(b)
        ctx.beginPath()
        ctx.moveTo(p1.x, p1.y)
        ctx.lineTo(p2.x, p2.y)
        ctx.stroke()
      }

      const pts = notesRef.current.map((n) => ({ n, p: project([n.x, n.y, n.z]) }))
      pts.sort((a, b) => a.p.depth - b.p.depth)
      st.projected = pts
      ctx.fillStyle = colors.dot
      for (const { n, p } of pts) {
        const isHover = hoveredRef.current?.id === n.id
        ctx.globalAlpha = Math.max(0.35, Math.min(1, 0.45 + 0.55 * ((p.depth + 1.75) / 3.5)))
        ctx.beginPath()
        ctx.arc(p.x, p.y, (isHover ? 8.5 : 5.5) * p.scale, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalAlpha = 1
      raf = requestAnimationFrame(draw)
    }

    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [])

  function onPointerDown(e) {
    const st = stateRef.current
    st.dragging = true
    st.lastX = e.clientX
    st.lastY = e.clientY
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function onPointerMove(e) {
    const st = stateRef.current
    if (st.dragging) {
      st.ry += (e.clientX - st.lastX) * 0.008
      st.rx = Math.max(-1.4, Math.min(1.4, st.rx + (e.clientY - st.lastY) * 0.008))
      st.lastX = e.clientX
      st.lastY = e.clientY
      return
    }
    const rect = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    let found = null
    for (let i = st.projected.length - 1; i >= 0; i--) {
      const { n, p } = st.projected[i]
      if ((p.x - mx) ** 2 + (p.y - my) ** 2 < 196) {
        found = n
        break
      }
    }
    onHover(found)
  }

  function onPointerUp() {
    stateRef.current.dragging = false
  }

  return (
    <div className="map-wrap">
      <canvas
        ref={canvasRef}
        className="map-canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => onHover(null)}
      />
    </div>
  )
}
