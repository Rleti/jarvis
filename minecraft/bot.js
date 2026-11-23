// Бот-напарник для Minecraft Java. Запускается Джарвисом, слушает команды на 127.0.0.1:<api>.
// node bot.js --host=localhost --port=54321 --name=Jarvis --api=3005
const http = require('http')
const mineflayer = require('mineflayer')
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder')
const pvp = require('mineflayer-pvp').plugin
const collectBlock = require('mineflayer-collectblock').plugin
const armorManager = require('mineflayer-armor-manager')
const { Vec3 } = require('vec3')
const { makePlan } = require('./plans')

const args = Object.fromEntries(process.argv.slice(2).map(a => a.replace(/^--/, '').split('=')))
const HOST = args.host || 'localhost'
const PORT = parseInt(args.port || '25565')
const NAME = args.name || 'Jarvis'
const API = parseInt(args.api || '3005')

const events = []                     // сообщения для Джарвиса — он их озвучит
const report = text => { events.push(text); console.log('[event]', text) }

// враждебные мобы на случай, если версия не помечает их type === 'hostile'
const HOSTILE = new Set(['zombie', 'husk', 'drowned', 'skeleton', 'stray', 'bogged', 'creeper', 'spider',
  'cave_spider', 'enderman', 'witch', 'slime', 'magma_cube', 'phantom', 'pillager', 'vindicator', 'evoker',
  'ravager', 'vex', 'blaze', 'ghast', 'hoglin', 'zoglin', 'piglin_brute', 'wither_skeleton', 'silverfish',
  'endermite', 'guardian', 'elder_guardian', 'shulker', 'breeze', 'zombie_villager', 'creaking'])

let ready = false
let mode = 'idle'       // idle | follow | guard | collect
let owner = null        // кого охраняем / за кем ходим

const bot = mineflayer.createBot({ host: HOST, port: PORT, username: NAME, auth: 'offline' })
bot.loadPlugin(pathfinder)
bot.loadPlugin(pvp)
bot.loadPlugin(collectBlock)
bot.loadPlugin(armorManager)            // сам надевает лучшую броню из инвентаря

bot.once('spawn', () => {
  const moves = new Movements(bot)
  bot.moves = moves
  moves.allowSprinting = true
  moves.canOpenDoors = true
  bot.pathfinder.setMovements(moves)
  bot.pathfinder.thinkTimeout = 15000      // по умолчанию 5 с — в лесу часто не хватает
  bot.pathfinder.tickTimeout = 40
  ready = true
  console.log('spawned, version', bot.version)
})
bot.on('death', () => report('Меня убили, возрождаюсь'))
bot.on('kicked', reason => { console.log('kicked', reason); report('Меня выкинули с сервера') })
bot.on('error', err => console.log('error:', err.message))
bot.on('end', () => { ready = false; console.log('end'); setTimeout(() => process.exit(0), 300) })

let lastLowHp = 0
bot.on('health', () => {
  if (bot.health < 8 && Date.now() - lastLowHp > 20000) {
    lastLowHp = Date.now()
    report('У меня мало здоровья')
  }
  autoEat()
})

// ---------- помощники ----------
const isHostile = e => e && e !== bot.entity && (e.type === 'hostile' || HOSTILE.has(e.name))

function findPlayer (name) {
  const others = Object.values(bot.players).filter(p => p.username !== bot.username)
  if (name) {
    const exact = others.find(p => p.username.toLowerCase() === name.toLowerCase())
    if (exact) return exact
  }
  if (owner && bot.players[owner]) return bot.players[owner]
  return others.find(p => p.entity) || others[0]
}

function stopAll () {
  mode = 'idle'
  try { bot.pvp.stop() } catch (e) {}
  bot.pathfinder.setGoal(null)
  try { if (bot.collectBlock.cancelTask) bot.collectBlock.cancelTask().catch(() => {}) } catch (e) {}
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

function withTimeout (promise, ms) {
  return Promise.race([promise, new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms))])
}

let eating = false
async function autoEat () {
  if (eating || bot.food >= 14 || !bot.registry.foodsByName) return
  const food = bot.inventory.items().find(i => bot.registry.foodsByName[i.name])
  if (!food) return
  eating = true
  try { await bot.equip(food, 'hand'); await bot.consume() } catch (e) {}
  eating = false
}

function blockIds (name) {
  const n = name.toLowerCase().trim().replace(/\s+/g, '_')
  const all = Object.values(bot.registry.blocksByName)
  if (['wood', 'log', 'logs', 'tree'].includes(n)) return all.filter(b => b.name.endsWith('_log')).map(b => b.id)
  if (bot.registry.blocksByName[n]) {
    // iron_ore -> ещё и deepslate_iron_ore
    return all.filter(b => b.name === n || b.name === 'deepslate_' + n).map(b => b.id)
  }
  return all.filter(b => b.name.includes(n)).map(b => b.id)
}

function countItems () {
  const totals = {}
  for (const i of bot.inventory.items()) totals[i.name] = (totals[i.name] || 0) + i.count
  return totals
}

// ---------- охрана ----------
setInterval(() => {
  if (!ready || mode !== 'guard') return
  const p = owner && bot.players[owner] && bot.players[owner].entity
  const center = p ? p.position : bot.entity.position
  const enemy = bot.nearestEntity(e => isHostile(e) && e.position.distanceTo(center) < 16)
  if (enemy) {
    if (bot.pvp.target !== enemy) bot.pvp.attack(enemy)
  } else if (p && !bot.pvp.target && bot.entity.position.distanceTo(p.position) > 4) {
    bot.pathfinder.setGoal(new goals.GoalFollow(p, 2), true)
  }
}, 400)

// ---------- долгие задачи ----------
async function collect (name, count) {
  const ids = blockIds(name)
  if (!ids.length) return report(`Не знаю такой блок: ${name}`)
  if (mode !== 'build') mode = 'collect'
  const keep = mode
  const before = countItems()
  const skip = new Set()          // блоки, до которых не дойти
  let done = 0
  let fails = 0
  while (mode === keep && done < count && fails < 4) {
    const block = bot.findBlock({
      matching: ids,
      maxDistance: 48,
      useExtraInfo: b => !skip.has(b.position.toString())
    })
    if (!block) break
    try {
      await withTimeout(bot.collectBlock.collect(block, { ignoreNoPath: false }), 30000)
      done++
      fails = 0
      console.log(`[collect] ${block.name} ${done}/${count}`)
      if (count >= 16 && done % 10 === 0 && done < count) report(`Добываю ${name}: ${done} из ${count}`)
    } catch (e) {
      console.log(`[collect] не смог ${block.name} в ${block.position}: ${e.message}`)
      skip.add(block.position.toString())
      fails++
      try { bot.pathfinder.setGoal(null) } catch (_) {}
    }
  }
  const after = countItems()
  const got = Object.keys(after).filter(k => (after[k] || 0) > (before[k] || 0))
    .map(k => `${k} ${after[k] - (before[k] || 0)}`).join(', ')
  if (got) report(`Добыл: ${got}`)
  else if (!done) report(`Не нашёл или не смог добыть ${name} поблизости`)
  else report(`Не смог добыть ${name}, возможно нужен инструмент`)
  if (mode === 'collect') mode = 'idle'
}

// ---------- крафт ----------
const have = id => bot.inventory.items().filter(i => i.type === id).reduce((s, i) => s + i.count, 0)
const ingredients = r => r.delta.filter(d => d.count < 0)

function findItem (name) {
  const n = name.toLowerCase().trim().replace(/\s+/g, '_')
  const items = bot.registry.itemsByName
  return items[n] || Object.values(items).find(i => i.name === 'wooden_' + n) ||
    Object.values(items).find(i => i.name.includes(n))
}

function nearTable () {
  return bot.findBlock({ matching: bot.registry.blocksByName.crafting_table.id, maxDistance: 32 })
}

// можно ли получить предмет: есть в инвентаре или скрафтить из того, что есть (до 3 шагов вглубь)
function canObtain (id, depth = 0) {
  if (have(id) > 0) return true
  if (depth > 3) return false
  return bot.recipesAll(id, null, true).some(r => ingredients(r).every(d => canObtain(d.id, depth + 1)))
}

// рецепт из данных самой игры: «3 birch_planks, 2 stick, нужен верстак»
function recipeText (item) {
  const rs = bot.recipesAll(item.id, null, true)
  if (!rs.length) return `${item.name} не крафтится`
  const r = rs.find(x => ingredients(x).every(d => canObtain(d.id))) || rs[0]
  const parts = ingredients(r).map(d => `${-d.count} ${bot.registry.items[d.id].name}`)
  return `${item.name}: ${parts.join(', ')}${r.requiresTable ? ', нужен верстак' : ''}, получается ${r.result.count} шт.`
}

function lackText (item, count) {
  const r = bot.recipesAll(item.id, null, true)[0]
  if (!r) return `${item.name} не крафтится`
  const times = Math.ceil(count / r.result.count)
  const lack = ingredients(r).filter(d => have(d.id) < -d.count * times)
    .map(d => `${bot.registry.items[d.id].name} нужно ${-d.count * times}, есть ${have(d.id)}`)
  return lack.length ? `не хватает: ${lack.join('; ')}` : 'не хватает материалов'
}

async function goNear (block) {
  const p = block.position
  try { await withTimeout(bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 2)), 20000) } catch (e) {}
}

async function ensureTable (depth) {
  let table = nearTable()
  if (table) return table
  if (!have(bot.registry.itemsByName.crafting_table.id)) await craftItem(bot.registry.itemsByName.crafting_table, 1, depth + 1)
  const item = bot.inventory.items().find(i => i.name === 'crafting_table')
  if (!item) throw new Error('не из чего сделать верстак')
  await bot.equip(item, 'hand')
  const me = bot.entity.position
  const base = bot.findBlock({
    matching: b => b.boundingBox === 'block',
    maxDistance: 4,
    useExtraInfo: b => {
      const above = bot.blockAt(b.position.offset(0, 1, 0))
      const d = b.position.offset(0.5, 1, 0.5).distanceTo(me)
      return above && above.name === 'air' && d > 1.3 && d < 4
    }
  })
  if (!base) throw new Error('некуда поставить верстак')
  await bot.placeBlock(base, new Vec3(0, 1, 0))
  table = nearTable()
  if (!table) throw new Error('не получилось поставить верстак')
  return table
}

async function craftItem (item, count, depth = 0) {
  if (depth > 4) throw new Error('слишком длинная цепочка крафта')
  // 1) крафтится прямо сейчас?
  let table = nearTable()
  let recipe = bot.recipesFor(item.id, null, 1, null)[0] || (table && bot.recipesFor(item.id, null, 1, table)[0])
  if (!recipe) {
    // 2) выбираем рецепт, все ингредиенты которого можно добыть из инвентаря, и делаем недостающие
    recipe = bot.recipesAll(item.id, null, true).find(r => ingredients(r).every(d => canObtain(d.id)))
    if (!recipe) throw new Error(lackText(item, count))
    const times = Math.ceil(count / recipe.result.count)
    // ингредиенты могут «съедать» друг друга (палки делаются из досок) — докрафчиваем в несколько кругов
    for (let round = 0; round < 4; round++) {
      const missing = ingredients(recipe).filter(d => have(d.id) < -d.count * times)
      if (!missing.length) break
      // сначала то, что само делается из других ингредиентов (палки), потом базовое (доски)
      const isBase = d => bot.registry.items[d.id].name.endsWith('_planks') ? 1 : 0
      missing.sort((a, b) => isBase(a) - isBase(b))
      for (const d of missing) {
        const need = -d.count * times - have(d.id)
        if (need > 0) await craftItem(bot.registry.items[d.id], need, depth + 1)
      }
    }
  }
  if (recipe.requiresTable) {
    table = await ensureTable(depth)
    await goNear(table)
    recipe = bot.recipesFor(item.id, null, 1, table)[0]
  } else {
    recipe = bot.recipesFor(item.id, null, 1, null)[0]
  }
  if (!recipe) throw new Error(lackText(item, count))
  await bot.craft(recipe, Math.ceil(count / recipe.result.count), recipe.requiresTable ? table : null)
}


// ---------- строительство ----------
const NEIGHBORS = [[0, -1, 0], [0, 1, 0], [1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1]]
const isAir = b => !b || b.name === 'air' || b.name === 'cave_air' || b.name === 'void_air'
const isSolid = b => b && b.boundingBox === 'block'
const isLiquid = b => b && (b.name === 'water' || b.name === 'lava')

function resolveMaterial (m) {
  const name = (m || 'planks').toLowerCase().trim().replace(/\s+/g, '_')
  const inv = bot.inventory.items()
  if (['planks', 'plank', 'wood', 'wooden', 'доски', 'дерево'].includes(name)) {
    const p = inv.find(i => i.name.endsWith('_planks'))
    if (p) return p.name
    const log = inv.find(i => i.name.endsWith('_log'))
    return log ? log.name.replace('_log', '_planks') : 'oak_planks'
  }
  if (name === 'stone' || name === 'камень') return 'cobblestone'
  if (bot.registry.itemsByName[name]) return name
  return Object.keys(bot.registry.itemsByName).find(n => n.includes(name)) || 'oak_planks'
}

function woodType (material) {
  return material.endsWith('_planks') ? material.replace('_planks', '') : 'oak'
}

// превращаем локальный план в мировые координаты перед игроком
function toWorld (plan, material, p) {
  const ref = p && p.entity ? p.entity : bot.entity
  const yaw = ref.yaw
  let fx = -Math.sin(yaw)
  let fz = -Math.cos(yaw)
  if (Math.abs(fx) > Math.abs(fz)) { fx = Math.sign(fx); fz = 0 } else { fz = Math.sign(fz); fx = 0 }
  const rx = -fz
  const rz = fx
  const base = ref.position.floored()
  const origin = base.offset(fx * 2, 0, fz * 2)
  const wood = woodType(material)
  const itemFor = it => it === 'MAT' ? material : it === 'DOOR' ? wood + '_door'
    : it === 'FENCE' ? wood + '_fence' : it === 'GATE' ? wood + '_fence_gate' : it
  const at = ({ u, y, v }) => origin.offset(rx * u + fx * v, y, rz * u + fz * v)
  return {
    blocks: plan.blocks.map(b => ({ pos: at(b), item: itemFor(b.item), optional: b.optional })),
    clear: plan.clear.map(at)
  }
}

async function goNearPos (pos, range = 3) {
  if (bot.entity.position.distanceTo(pos.offset(0.5, 0.5, 0.5)) <= range + 0.8) return
  try { await withTimeout(bot.pathfinder.goto(new goals.GoalNear(pos.x, pos.y, pos.z, range)), 12000) } catch (e) {
    try { bot.pathfinder.setGoal(null) } catch (_) {}
  }
}

async function stepAside (pos) {
  const feet = bot.entity.position.floored()
  if (feet.equals(pos) || feet.offset(0, 1, 0).equals(pos)) {
    try {
      await withTimeout(bot.pathfinder.goto(new goals.GoalInvert(new goals.GoalNear(pos.x, pos.y, pos.z, 1.5))), 8000)
    } catch (e) {}
  }
}

// добыть/скрафтить нужное количество предметов для постройки
async function ensureItems (name, n) {
  if (have(bot.registry.itemsByName[name].id) >= n) return
  const missing = () => n - have(bot.registry.itemsByName[name].id)
  if (name.endsWith('_planks')) {
    const log = name.replace('_planks', '_log')
    const logs = have((bot.registry.itemsByName[log] || {}).id)
    const needLogs = Math.ceil(missing() / 4) - logs
    if (needLogs > 0) {
      report(`Не хватает досок, иду рубить дерево`)
      await collect(bot.registry.itemsByName[log] ? log : 'wood', needLogs + 1)
    }
    try { await craftItem(bot.registry.itemsByName[name], missing()) } catch (e) {}
    return
  }
  if (/_(door|fence|fence_gate)$/.test(name)) {
    try { await craftItem(bot.registry.itemsByName[name], missing()) } catch (e) {
      // не хватает досок — добудем и попробуем ещё раз
      await ensureItems(name.replace(/_(door|fence|fence_gate)$/, '_planks'), Math.min(64, missing() * 6))
      try { await craftItem(bot.registry.itemsByName[name], missing()) } catch (_) {}
    }
    return
  }
  if (name === 'cobblestone') return collect('stone', missing())
  if (name === 'dirt') return collect('dirt', missing())
}

async function clearAt (pos) {
  const b = bot.blockAt(pos)
  if (isAir(b) || isLiquid(b)) return
  await goNearPos(pos, 3)
  try {
    if (bot.tool && bot.tool.equipForBlock) await bot.tool.equipForBlock(b)
    await bot.dig(b)
  } catch (e) {}
}

async function placeAt (pos, item) {
  const cur = bot.blockAt(pos)
  if (!cur) throw new Error('далеко')
  if (cur.name === item) return 'done'
  if (isSolid(cur)) return 'done'                  // уже что-то твёрдое — считаем частью стены
  const invItem = bot.inventory.items().find(i => i.name === item)
  if (!invItem) throw new Error('NOITEM')
  if (!isAir(cur) && !isLiquid(cur)) await clearAt(pos)  // трава, цветы
  const refOffset = NEIGHBORS.find(([x, y, z]) => isSolid(bot.blockAt(pos.offset(x, y, z))))
  if (!refOffset) throw new Error('NOSUPPORT')
  await goNearPos(pos, 3)
  if (bot.entity.position.distanceTo(pos.offset(0.5, 0.5, 0.5)) > 5.5) throw new Error('FAR')
  await stepAside(pos)
  const ref = bot.blockAt(pos.offset(...refOffset))
  await bot.equip(invItem, 'hand')
  await bot.placeBlock(ref, new Vec3(-refOffset[0], -refOffset[1], -refOffset[2]))
  return 'placed'
}

async function build (type, size, height, materialName) {
  const plan = makePlan(type, size, height)
  if (!plan) return report(`Не умею строить «${type}»`)
  const p = findPlayer(owner)
  const material = resolveMaterial(materialName)
  const world = toWorld(plan, material, p)
  mode = 'build'

  // защищаем свою постройку от лопаты собственного навигатора
  const protect = [material, woodType(material) + '_door', woodType(material) + '_fence']
    .map(n => bot.registry.blocksByName[n]).filter(Boolean).map(b => b.id)
  protect.forEach(id => bot.moves.blocksCantBreak.add(id))

  // сколько чего нужно
  const need = {}
  for (const b of world.blocks) {
    if (isSolid(bot.blockAt(b.pos))) continue
    need[b.item] = (need[b.item] || 0) + 1
  }
  report(`Строю ${plan.label} из ${material}. Нужно блоков: ${need[material] || 0}`)
  for (const [item, n] of Object.entries(need)) {
    if (mode !== 'build') break
    if (item === 'glass' || item === 'torch') continue           // окна без стекла будут просто проёмами
    if (bot.registry.itemsByName[item]) {
      try { await ensureItems(item, n) } catch (e) { console.log('ensureItems', item, e.message) }
    }
  }

  console.log(`[build] ${plan.label}: блоков ${world.blocks.length}, расчистка ${world.clear.length}, материалы`, JSON.stringify(need),
    'в инвентаре', JSON.stringify(countItems()))
  for (const pos of world.clear.sort((a, b) => b.y - a.y)) {
    if (mode !== 'build') break
    await clearAt(pos)
  }
  console.log('[build] расчистка готова')
  let placed = 0

  let pending = world.blocks.slice().sort((a, b) => a.pos.y - b.pos.y)
  const lacking = new Set()
  for (let pass = 0; pass < 4 && pending.length && mode === 'build'; pass++) {
    const next = []
    for (const b of pending) {
      if (mode !== 'build') break
      if (lacking.has(b.item)) { if (!b.optional) next.push(b); continue }
      try {
        if (await placeAt(b.pos, b.item) === 'placed') {
          placed++
          if (placed % 15 === 0) report(`Стройка идёт: поставил ${placed} блоков`)
        }
      } catch (e) {
        console.log(`[build] не поставил ${b.item} в ${b.pos}: ${e.message}`)
        if (e.message === 'NOITEM') {
          lacking.add(b.item)
          if (b.optional) continue
        }
        next.push(b)
      }
    }
    pending = next
    console.log(`[build] проход ${pass + 1}: осталось ${pending.length}`)
  }
  protect.forEach(id => bot.moves.blocksCantBreak.delete(id))
  if (mode !== 'build') return report('Стройку остановил')
  mode = 'idle'
  const main = pending.filter(b => !b.optional)
  if (!main.length) report(`Построил ${plan.label}`)
  else if (lacking.has(material)) report(`Не хватило ${material}, осталось поставить ${main.length} блоков`)
  else report(`Построил ${plan.label}, но ${main.length} блоков поставить не смог`)
}


// ---------- действия игрока ----------
const TOOLS_RE = /(_sword|_pickaxe|_axe|_shovel|_hoe|_helmet|_chestplate|_leggings|_boots|shield|bow|crossbow|trident)$/

async function placeNearMe (itemName) {
  const item = bot.inventory.items().find(i => i.name === itemName) ||
    bot.inventory.items().find(i => i.name.includes(itemName))
  if (!item) throw new Error(`у меня нет ${itemName}`)
  await bot.equip(item, 'hand')
  const me = bot.entity.position
  const base = bot.findBlock({
    matching: b => b.boundingBox === 'block',
    maxDistance: 4,
    useExtraInfo: b => {
      const above = bot.blockAt(b.position.offset(0, 1, 0))
      const d = b.position.offset(0.5, 1, 0.5).distanceTo(me)
      return isAir(above) && d > 1.3 && d < 4
    }
  })
  if (!base) throw new Error('некуда поставить')
  await bot.placeBlock(base, new Vec3(0, 1, 0))
  return base.position.offset(0, 1, 0)
}

async function pickupNear (center, radius) {
  const before = countItems()
  const drops = Object.values(bot.entities)
    .filter(e => e.name === 'item' && e.position.distanceTo(center) < radius)
    .sort((a, b) => a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position))
  for (const e of drops) {
    if (!bot.entities[e.id]) continue
    const p = e.position
    try { await withTimeout(bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 0.8)), 10000) } catch (_) {}
    await sleep(250)
  }
  const after = countItems()
  return Object.keys(after).filter(k => after[k] > (before[k] || 0)).map(k => `${k} ${after[k] - (before[k] || 0)}`).join(', ')
}

const CROPS = {
  wheat: { max: 7, seed: 'wheat_seeds' },
  carrots: { max: 7, seed: 'carrot' },
  potatoes: { max: 7, seed: 'potato' },
  beetroots: { max: 3, seed: 'beetroot_seeds' }
}
const cropAge = b => { try { return b.getProperties().age } catch (e) { return b.metadata } }

async function farm () {
  mode = 'farm'
  let harvested = 0
  let replanted = 0
  while (mode === 'farm') {
    const crop = bot.findBlock({ matching: b => CROPS[b.name] && cropAge(b) >= CROPS[b.name].max, maxDistance: 24 })
    if (!crop) break
    const pos = crop.position.clone()
    const info = CROPS[crop.name]
    await goNear(crop)
    try { await bot.dig(crop) } catch (e) { break }
    harvested++
    await sleep(300)
    await pickupNear(pos, 4)
    const seed = bot.inventory.items().find(i => i.name === info.seed)
    const soil = bot.blockAt(pos.offset(0, -1, 0))
    if (seed && soil && soil.name === 'farmland') {
      try { await bot.equip(seed, 'hand'); await bot.placeBlock(soil, new Vec3(0, 1, 0)); replanted++ } catch (e) {}
    }
  }
  if (mode === 'farm') mode = 'idle'
  report(harvested ? `Собрал урожай с ${harvested} грядок, пересадил ${replanted}` : 'Спелого урожая рядом нет')
}

async function smelt (name, count) {
  const input = bot.inventory.items().find(i => i.name.includes(name))
  if (!input) return report(`У меня нет ${name} для переплавки`)
  const fuel = bot.inventory.items().find(i => ['coal', 'charcoal', 'coal_block'].includes(i.name)) ||
    bot.inventory.items().find(i => /_(planks|log)$/.test(i.name) && i.type !== input.type)
  if (!fuel) return report('Нет топлива: нужен уголь, доски или брёвна')
  mode = 'smelt'
  try {
    let fb = bot.findBlock({ matching: bot.registry.blocksByName.furnace.id, maxDistance: 32 })
    if (!fb) {
      if (!have(bot.registry.itemsByName.furnace.id)) await craftItem(bot.registry.itemsByName.furnace, 1)
      fb = bot.blockAt(await placeNearMe('furnace'))
    }
    await goNear(fb)
    const f = await bot.openFurnace(fb)
    const n = Math.min(count || input.count, input.count)
    const perFuel = fuel.name.includes('coal') ? 8 : 1.5
    await f.putFuel(fuel.type, null, Math.min(fuel.count, Math.ceil(n / perFuel)))
    await f.putInput(input.type, null, n)
    report(`Плавлю ${input.name} ${n}, это около ${Math.ceil(n * 10 / 60)} мин`)
    const deadline = Date.now() + n * 10500 + 8000
    while (Date.now() < deadline && mode === 'smelt') {
      await sleep(2000)
      if (!f.inputItem() && f.outputItem()) break
    }
    const out = f.outputItem()
    if (out) await f.takeOutput()
    f.close()
    report(out ? `Переплавил: ${out.name} ${out.count}` : 'Ничего не переплавилось')
  } catch (e) {
    report(`Не получилось переплавить: ${e.message}`)
  }
  if (mode === 'smelt') mode = 'idle'
}

async function chestOp (kind, name, count) {
  const cb = bot.findBlock({ matching: b => ['chest', 'trapped_chest', 'barrel'].includes(b.name), maxDistance: 24 })
  if (!cb) return 'Рядом нет сундука'
  await goNear(cb)
  const c = await bot.openContainer(cb)
  try {
    if (kind === 'deposit') {
      const items = bot.inventory.items().filter(i => name ? i.name.includes(name) : !TOOLS_RE.test(i.name))
      let n = 0
      for (const it of items) {
        const k = count ? Math.min(count - n, it.count) : it.count
        if (k <= 0) break
        try { await c.deposit(it.type, null, k); n += k } catch (e) {}
      }
      return n ? `Положил в сундук ${n} шт.` : 'Нечего класть'
    }
    const items = c.containerItems().filter(i => !name || i.name.includes(name))
    if (!items.length) return name ? `В сундуке нет ${name}` : 'Сундук пуст'
    let n = 0
    for (const it of items) {
      const k = count ? Math.min(count - n, it.count) : it.count
      if (k <= 0) break
      try { await c.withdraw(it.type, null, k); n += k } catch (e) {}
    }
    return `Взял из сундука ${n} шт.`
  } finally {
    c.close()
  }
}

// ---------- команды ----------
const queue = []          // дела, которые ждут окончания текущего
const BUSY = { build: 'строю', collect: 'добываю', smelt: 'плавлю', farm: 'собираю урожай' }

// берём следующее дело из очереди, когда бот освободился
setInterval(async () => {
  if (!ready || BUSY[mode] || !queue.length || queueRunning) return
  queueRunning = true
  const t = queue.shift()
  try {
    const r = await handle(t.action, t.target, t.count, t.material, t.height, true)
    report(/^(Начал|Пошёл|Иду)/.test(r) ? `Приступаю к следующему делу: ${t.action} ${t.target}` : r)
  } catch (e) {
    report(`Не получилось ${t.action}: ${e.message}`)
  }
  queueRunning = false
}, 1000)
let queueRunning = false

async function handle (action, target, count, material, height, fromQueue = false) {
  if (!ready) return 'Ещё захожу в игру, подожди'
  const QUICK = ['status', 'inventory', 'recipe', 'stop', 'say', 'leave', 'equip', 'eat']
  if (action === 'stop') queue.length = 0
  if (BUSY[mode] && !QUICK.includes(action) && !fromQueue) {
    queue.push({ action, target, count, material, height })
    return `Сейчас ${BUSY[mode]}. Поставил в очередь под номером ${queue.length}: ${action} ${target}. Сделаю сразу после текущего дела`
  }
  const p = findPlayer(target)
  switch (action) {
    case 'follow': {
      if (!p || !p.entity) return 'Не вижу тебя, подойди ближе'
      stopAll(); mode = 'follow'; owner = p.username
      bot.pathfinder.setGoal(new goals.GoalFollow(p.entity, 2), true)
      return `Иду за ${p.username}`
    }
    case 'come': {
      if (!p || !p.entity) return 'Не вижу тебя, подойди ближе'
      stopAll()
      const pos = p.entity.position
      bot.pathfinder.setGoal(new goals.GoalNear(pos.x, pos.y, pos.z, 1))
      return 'Иду к тебе'
    }
    case 'stop':
      stopAll()
      return 'Стою'
    case 'guard': {
      stopAll(); mode = 'guard'; owner = p ? p.username : null
      return owner ? `Охраняю ${owner}` : 'Охраняю это место'
    }
    case 'attack': {
      const t = target.toLowerCase()
      const enemy = bot.nearestEntity(e => e !== bot.entity && e.position.distanceTo(bot.entity.position) < 32 &&
        (t ? (e.name || '').includes(t) || (e.username || '').toLowerCase() === t : isHostile(e)))
      if (!enemy) return t ? `Не вижу ${target} рядом` : 'Врагов рядом нет'
      bot.pvp.attack(enemy)
      return `Атакую ${enemy.username || enemy.name}`
    }
    case 'collect': {
      if (!target) return 'Что добывать?'
      stopAll()
      collect(target, Math.max(1, Math.min(count || 10, 48)))   // в фоне, результат придёт сообщением
      return `Пошёл добывать ${target}. Результат сообщу отдельно, когда закончу`
    }
    case 'build': {
      if (!target) return 'Что строить?'
      if (!makePlan(target, 0, 0)) return `Не умею строить «${target}». Умею: дом, укрытие, стену, башню, столб, платформу, мост, загон`
      stopAll()
      build(target, count || 0, height || 0, material)   // в фоне, о результате сообщу
      return `Начал строить ${target}. Это займёт несколько минут, о готовности сообщу отдельно`
    }
    case 'craft': {
      const item = target && findItem(target)
      if (!item) return target ? `Не знаю предмет ${target}` : 'Что скрафтить?'
      stopAll()
      const n = Math.max(1, Math.min(count || 1, 64))
      try {
        await withTimeout(craftItem(item, n), 60000)
        return `Скрафтил: ${item.name} ${n}`
      } catch (e) {
        return `Не получилось скрафтить ${item.name}: ${e.message}. Рецепт: ${recipeText(item)}`
      }
    }
    case 'recipe': {
      const item = target && findItem(target)
      if (!item) return target ? `Не знаю предмет ${target}` : 'Рецепт чего?'
      return recipeText(item)
    }
    case 'give': {
      if (!p || !p.entity) return 'Не вижу тебя, подойди ближе'
      const items = bot.inventory.items().filter(i => !target || i.name.includes(target.toLowerCase()))
      if (!items.length) return target ? `У меня нет ${target}` : 'Инвентарь пуст'
      stopAll()
      try {
        await withTimeout(bot.pathfinder.goto(new goals.GoalFollow(p.entity, 2)), 20000)
      } catch (e) {}
      await bot.lookAt(p.entity.position.offset(0, 1.6, 0))
      const item = items[0]
      const total = items.filter(i => i.type === item.type).reduce((s, i) => s + i.count, 0)
      const n = Math.min(count || total, total)
      await bot.toss(item.type, null, n)
      return `Держи: ${item.name} ${n}`
    }
    case 'inventory': {
      const t = countItems()
      const list = Object.entries(t).map(([k, v]) => `${k} ${v}`).join(', ')
      return list || 'Инвентарь пуст'
    }
    case 'status': {
      const pos = bot.entity.position
      const time = bot.time.timeOfDay
      const day = time < 12500 ? 'день' : 'ночь'
      return `Здоровье ${Math.round(bot.health)} из 20, сытость ${bot.food} из 20, ` +
        `координаты ${Math.round(pos.x)} ${Math.round(pos.y)} ${Math.round(pos.z)}, сейчас ${day}, занят: ${BUSY[mode] || 'ничем'}` +
        (queue.length ? `, в очереди: ${queue.map(t => t.action + ' ' + t.target).join(', ')}` : '')
    }
    case 'pickup': {
      stopAll()
      const got = await pickupNear(bot.entity.position, 24)
      return got ? `Подобрал: ${got}` : 'Рядом ничего не валяется'
    }
    case 'equip': {
      const item = bot.inventory.items().find(i => i.name.includes((target || '').toLowerCase()))
      if (!item) return `У меня нет ${target}`
      const dest = /_helmet$/.test(item.name) ? 'head' : /_chestplate$|elytra/.test(item.name) ? 'torso'
        : /_leggings$/.test(item.name) ? 'legs' : /_boots$/.test(item.name) ? 'feet' : /shield/.test(item.name) ? 'off-hand' : 'hand'
      await bot.equip(item, dest)
      return `Взял ${item.name}`
    }
    case 'eat': {
      if (bot.food >= 20) return 'Я не голоден'
      const food = bot.inventory.items().find(i => bot.registry.foodsByName && bot.registry.foodsByName[i.name])
      if (!food) return 'Еды нет'
      await bot.equip(food, 'hand')
      await bot.consume()
      return `Съел ${food.name}`
    }
    case 'drop': {
      const items = bot.inventory.items().filter(i => !target || i.name.includes(target.toLowerCase()))
      if (!items.length) return target ? `У меня нет ${target}` : 'Инвентарь пуст'
      const item = items[0]
      await bot.toss(item.type, null, Math.min(count || item.count, item.count))
      return `Выбросил ${item.name}`
    }
    case 'goto': {
      const nums = (target.match(/-?\d+/g) || []).map(Number)
      if (nums.length < 2) return 'Скажи координаты: x y z или x z'
      stopAll()
      const goal = nums.length >= 3 ? new goals.GoalNear(nums[0], nums[1], nums[2], 1) : new goals.GoalXZ(nums[0], nums[1])
      bot.pathfinder.setGoal(goal)
      return `Иду на ${nums.join(' ')}`
    }
    case 'place': {
      if (!target) return 'Что поставить?'
      try {
        const pos = await placeNearMe(target.toLowerCase())
        return `Поставил ${target} на ${pos.x} ${pos.y} ${pos.z}`
      } catch (e) { return `Не получилось поставить: ${e.message}` }
    }
    case 'sleep': {
      const bed = bot.findBlock({ matching: b => b.name.endsWith('_bed'), maxDistance: 32 })
      if (!bed) return 'Рядом нет кровати'
      stopAll()
      await goNear(bed)
      try { await bot.sleep(bed); return 'Лёг спать' } catch (e) { return `Не могу лечь: ${e.message}` }
    }
    case 'smelt': {
      if (!target) return 'Что переплавить?'
      stopAll()
      smelt(target.toLowerCase(), count)
      return `Иду плавить ${target}. Результат сообщу отдельно`
    }
    case 'farm': {
      stopAll()
      farm()
      return 'Иду собирать урожай. Результат сообщу отдельно'
    }
    case 'deposit':
    case 'withdraw': {
      stopAll()
      try { return await chestOp(action, (target || '').toLowerCase(), count) } catch (e) { return `Не получилось с сундуком: ${e.message}` }
    }
    case 'say':
      bot.chat(target.slice(0, 250))
      return 'Написал в чат'
    case 'leave':
      stopAll()
      setTimeout(() => bot.quit(), 300)
      return 'Выхожу из игры'
    default:
      return `Неизвестная команда ${action}`
  }
}

// ---------- API для Джарвиса ----------
http.createServer((req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  if (req.method === 'GET' && req.url === '/status') return res.end(JSON.stringify({ ready, mode }))
  if (req.method === 'GET' && req.url === '/events') return res.end(JSON.stringify(events.splice(0)))
  let body = ''
  req.on('data', c => { body += c })
  req.on('end', async () => {
    let text
    try {
      const { action, target, count, material, height } = JSON.parse(body || '{}')
      text = await handle(action, target || '', count || 0, material || '', height || 0)
    } catch (e) {
      text = 'Ошибка: ' + e.message
    }
    res.end(JSON.stringify({ text: String(text) }))
  })
}).listen(API, '127.0.0.1', () => console.log('api on', API))
