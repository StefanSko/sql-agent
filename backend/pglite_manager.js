const fs = require('node:fs/promises')
const { PGlite } = require('@electric-sql/pglite')
const { PGLiteSocketServer } = require('@electric-sql/pglite-socket')

function argument(name) {
  const index = process.argv.indexOf(name)
  if (index < 0 || index + 1 >= process.argv.length) {
    throw new Error(`missing required argument ${name}`)
  }
  return process.argv[index + 1]
}

async function main() {
  const dbPath = argument('--db')
  const port = Number.parseInt(argument('--port'), 10)
  const readyFile = argument('--ready-file')
  const db = await PGlite.create(dbPath)
  const server = new PGLiteSocketServer({
    db,
    host: '127.0.0.1',
    port,
    inspect: process.env.PGLITE_INSPECT === '1',
    maxConnections: 10,
  })

  let stopping = false
  async function stop() {
    if (stopping) return
    stopping = true
    await server.stop()
    await db.close()
    process.exit(0)
  }

  process.on('SIGINT', stop)
  process.on('SIGTERM', stop)
  await server.start()
  await fs.writeFile(readyFile, `${port}\n`, { encoding: 'utf8' })
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
