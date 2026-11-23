// Планы построек в локальных координатах:
//   u — вправо от игрока, v — вперёд от игрока, y — вверх от уровня ног.
// Каждый план: { label, blocks: [{u, y, v, item, optional}], clear: [{u, y, v}] }
// item может быть 'MAT' (основной материал), 'DOOR', 'FENCE', 'GATE' или конкретный id ('glass').

const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x))

function house (size, height, withWindows) {
  const s = clamp(size, 4, 11)
  const h = clamp(height, 2, 6)
  const umin = -Math.floor(s / 2)
  const umax = umin + s - 1
  const vmax = s - 1
  const vmid = Math.floor(vmax / 2)
  const blocks = []
  const clear = []
  for (let y = 0; y < h; y++) {
    for (let u = umin; u <= umax; u++) {
      for (let v = 0; v <= vmax; v++) {
        const edge = u === umin || u === umax || v === 0 || v === vmax
        if (!edge) { clear.push({ u, y, v }); continue }
        const corner = (u === umin || u === umax) && (v === 0 || v === vmax)
        if (u === 0 && v === 0 && y < 2) {          // дверной проём спереди
          if (y === 0) blocks.push({ u, y, v, item: 'DOOR', optional: true })
          else clear.push({ u, y, v })
          continue
        }
        const window = withWindows && y === 1 && !corner &&
          (((u === umin || u === umax) && v === vmid) || (v === vmax && u === 0))
        blocks.push(window ? { u, y, v, item: 'glass', optional: true } : { u, y, v, item: 'MAT' })
      }
    }
  }
  for (let u = umin; u <= umax; u++) {
    for (let v = 0; v <= vmax; v++) blocks.push({ u, y: h, v, item: 'MAT' })   // плоская крыша
  }
  // проёмы окон без стекла остаются открытыми — их тоже расчищаем
  return { blocks, clear }
}

function makePlan (type, size, height) {
  const t = (type || '').toLowerCase()
  switch (t) {
    case 'house': case 'home': case 'дом':
      return { label: 'дом', ...house(size || 5, height || 3, true) }
    case 'shelter': case 'hut': case 'укрытие':
      return { label: 'укрытие', ...house(size || 4, height || 2, false) }
    case 'wall': case 'стена': {
      const L = clamp(size || 7, 2, 32)
      const H = clamp(height || 3, 1, 10)
      const blocks = []
      const u0 = -Math.floor(L / 2)
      for (let y = 0; y < H; y++) for (let u = u0; u < u0 + L; u++) blocks.push({ u, y, v: 2, item: 'MAT' })
      return { label: 'стену', blocks, clear: [] }
    }
    case 'tower': case 'башня': {
      const H = clamp(height || size || 8, 3, 16)
      const blocks = []
      const clear = []
      for (let y = 0; y < H; y++) {
        for (let u = -1; u <= 1; u++) {
          for (let v = 0; v <= 2; v++) {
            if (u === 0 && v === 1) { clear.push({ u, y, v }); continue }
            if (u === 0 && v === 0 && y < 2) {
              if (y === 0) blocks.push({ u, y, v, item: 'DOOR', optional: true })
              else clear.push({ u, y, v })
              continue
            }
            blocks.push({ u, y, v, item: 'MAT' })
          }
        }
      }
      for (let u = -2; u <= 2; u++) for (let v = -1; v <= 3; v++) blocks.push({ u, y: H, v, item: 'MAT' })  // площадка сверху
      return { label: 'башню', blocks, clear }
    }
    case 'pillar': case 'column': case 'столб': {
      const H = clamp(height || size || 5, 1, 24)
      const blocks = []
      for (let y = 0; y < H; y++) blocks.push({ u: 0, y, v: 2, item: 'MAT' })
      return { label: 'столб', blocks, clear: [] }
    }
    case 'platform': case 'floor': case 'платформа': {
      const s = clamp(size || 5, 2, 16)
      const blocks = []
      const u0 = -Math.floor(s / 2)
      for (let u = u0; u < u0 + s; u++) for (let v = 1; v <= s; v++) blocks.push({ u, y: -1, v, item: 'MAT' })
      return { label: 'платформу', blocks, clear: [] }
    }
    case 'bridge': case 'мост': {
      const L = clamp(size || 10, 2, 64)
      const blocks = []
      for (let v = 1; v <= L; v++) for (let u = 0; u <= 1; u++) blocks.push({ u, y: -1, v, item: 'MAT' })
      return { label: 'мост', blocks, clear: [] }
    }
    case 'pen': case 'fence': case 'enclosure': case 'загон': {
      const s = clamp(size || 7, 3, 20)
      const blocks = []
      const umin = -Math.floor(s / 2)
      const umax = umin + s - 1
      for (let u = umin; u <= umax; u++) {
        for (let v = 1; v <= s; v++) {
          const edge = u === umin || u === umax || v === 1 || v === s
          if (!edge) continue
          blocks.push({ u, y: 0, v, item: u === 0 && v === 1 ? 'GATE' : 'FENCE' })
        }
      }
      return { label: 'загон', blocks, clear: [] }
    }
    default:
      return null
  }
}

const TYPES = 'house, shelter, wall, tower, pillar, platform, bridge, pen'

module.exports = { makePlan, TYPES }
