import { readFile, writeFile } from 'fs/promises'
import { join } from 'path'
import { homedir } from 'os'
import { createDecipheriv, createCipheriv, randomBytes } from 'crypto'

const ALG = 'aes-256-gcm'
const KEY_BYTES = 32
const IV_BYTES = 12

async function readKey() {
  const raw = (await readFile(join(homedir(), '.openalice', 'sealing.key'), 'utf-8')).trim()
  const key = Buffer.from(raw, 'base64')
  if (key.length !== KEY_BYTES) throw new Error(`key length ${key.length} != ${KEY_BYTES}`)
  return key
}

const accountsPath = join(homedir(), '.openalice', 'data', 'config', 'accounts.json')
const envelope = JSON.parse(await readFile(accountsPath, 'utf-8'))

const key = await readKey()

// Decrypt
const decipher = createDecipheriv(ALG, key, Buffer.from(envelope.iv, 'base64'))
decipher.setAuthTag(Buffer.from(envelope.tag, 'base64'))
const plaintext = Buffer.concat([
  decipher.update(Buffer.from(envelope.data, 'base64')),
  decipher.final(),
])
const accounts = JSON.parse(plaintext.toString('utf-8'))

console.log('Current accounts:')
accounts.forEach(a => console.log(`  ${a.id} (${a.presetId}) enabled=${a.enabled}`))

// Disable okx-readonly
const okx = accounts.find(a => a.presetId === 'okx-readonly')
if (okx) {
  okx.enabled = false
  console.log('\nDisabled okx-readonly')
} else {
  console.log('\nokx-readonly not found')
  process.exit(1)
}

// Re-encrypt
const iv = randomBytes(IV_BYTES)
const cipher = createCipheriv(ALG, key, iv)
const data = Buffer.concat([cipher.update(Buffer.from(JSON.stringify(accounts, null, 2))), cipher.final()])
const tag = cipher.getAuthTag()

const sealed = {
  $sealed: 1,
  alg: ALG,
  iv: iv.toString('base64'),
  tag: tag.toString('base64'),
  data: data.toString('base64'),
}

await writeFile(accountsPath, JSON.stringify(sealed, null, 2) + '\n', { mode: 0o600 })
console.log('✅ accounts.json updated')
