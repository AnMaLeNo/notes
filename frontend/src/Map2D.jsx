function truncate(s, n) {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

export default function Map2D({ notes, hovered, onHover }) {
  return (
    <div className="map-wrap">
      <svg
        className="map-svg"
        viewBox="-1.25 -1.25 2.5 2.5"
        onMouseLeave={() => onHover(null)}
      >
        <line x1="-1.18" y1="0" x2="1.18" y2="0" className="map-axis" />
        <line x1="0" y1="-1.18" x2="0" y2="1.18" className="map-axis" />
        {notes.map((n) => {
          const active = hovered?.id === n.id
          return (
            <g key={n.id} className="map-point" onMouseEnter={() => onHover(n)}>
              <circle
                cx={n.x}
                cy={-n.y}
                r={active ? 0.055 : 0.038}
                className={active ? 'map-dot active' : 'map-dot'}
              />
              <text x={n.x} y={-n.y - 0.08} textAnchor="middle" className="map-label">
                {truncate(n.content, 24)}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
