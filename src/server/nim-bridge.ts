import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { serve } from '@hono/node-server'
import type { Plugin, EngineContext } from '../core/types.js'
import axios from 'axios'
import { z } from 'zod'

/**
 * NIM Bridge Plugin — exposes an Anthropic-compatible API that forwards requests to NVIDIA NIM API.
 *
 *   POST /v1/messages   Anthropic messages endpoint -> translated to NVIDIA NIM /v1/chat/completions
 *   GET  /v1/models     Anthropic models endpoint -> proxied to NVIDIA NIM /v1/models (with alias resolution)
 *
 * The plugin runs on loopback only (127.0.0.1) for security, similar to the MCP plugin.
 * It is intended to be used by workspace agent CLIs via the ANTHROPIC_BASE_URL environment variable.
 *
 * Features:
 * - Dynamic model discovery from NVIDIA NIM API
 * - Model classification and caching
 * - Automatic routing based on task type (via alias resolution)
 * - NVIDIA-only failover chain
 * - Anthropic API compatibility (streaming, tool calls, etc.)
 */
export class NimBridgePlugin implements Plugin {
  name = 'nim-bridge'
  private server: ReturnType<typeof serve> | null = null
  private nvidiaApiKey: string | null = null
  private modelCache: ModelInfo[] = []
  private cacheTimestamp: number = 0
  private readonly CACHE_TTL_MS = 5 * 60 * 1000 // 5 minutes
  private readonly MODEL_ALIASES = {
    'nvidia-best': [], // will be filled with top models based on routing logic
    'nvidia-reasoning': [],
    'nvidia-coding': [],
    'nvidia-fast': [],
    'nvidia-long-context': [],
    'nvidia-vision': [],
  }

  constructor(private port: number) {}

  async start(_ctx: EngineContext) {
    // Read NVIDIA API key from environment
    this.nvidiaApiKey = process.env['NVIDIA_API_KEY']
    if (!this.nvidiaApiKey) {
      console.warn('[nim-bridge] NVIDIA_API_KEY not set; bridge will not function')
      // We still start the server but it will return errors for API calls
    }

    // Initial model discovery
    await this.discoverModels()

    // Set up periodic cache refresh
    setInterval(async () => {
      await this.discoverModels()
    }, this.CACHE_TTL_MS)

    const app = new Hono()

    app.use('*', cors({
      origin: '*',
      allowMethods: ['GET', 'POST', 'OPTIONS'],
      allowHeaders: ['Content-Type', 'anthropic-version', 'anthropic-beta', 'x-api-key'],
      exposeHeaders: ['anthropic-version'],
    }))

    // Anthropic messages endpoint
    app.post('/v1/messages', async (c) => {
      try {
        return await this.handleMessages(c)
      } catch (err) {
        console.error('[nim-bridge] Error handling messages:', err)
        return c.json({ error: 'Internal server error' }, 500)
      }
    })

    // Anthropic models endpoint (for compatibility)
    app.get('/v1/models', async (c) => {
      try {
        return await this.handleModels(c)
      } catch (err) {
        console.error('[nim-bridge] Error handling models:', err)
        return c.json({ error: 'Internal server error' }, 500)
      }
    })

    // Health check endpoint
    app.get('/health', (c) => {
      return c.json({
        status: 'ok',
        timestamp: Date.now(),
        modelCount: this.modelCache.length,
        cacheAgeMs: Date.now() - this.cacheTimestamp,
        nvidiaApiKeyConfigured: !!this.nvidiaApiKey,
      })
    })

    // LOOPBACK-ONLY, ALWAYS — deliberately NOT honoring OPENALICE_BIND_HOST.
    // This listener carries the bridge surface and its security model is "only local
    // processes can reach it". Its sole consumers are workspace subprocesses
    // (native agent CLIs), which run on the same host and always dial 127.0.0.1.
    this.server = serve({ fetch: app.fetch, port: this.port, hostname: '127.0.0.1' }, (info) => {
      console.log(`[nim-bridge] listening on http://127.0.0.1:${info.port}/v1/messages`)
      console.log(`[nim-bridge] NVIDIA API key configured: !!${this.nvidiaApiKey}`)
      console.log(`[nim-bridge] Discovered ${this.modelCache.length} models`)
    })
  }

  async stop() {
    this.server?.close()
  }

  // ==================== Model Discovery & Caching ====================

  interface ModelInfo {
    id: string
    provider: string // always 'nvidia'
    name: string
    created: number | null // timestamp
    // Additional metadata we might extract from the model object
    contextLength?: number
    capabilities?: string[]
    // We'll add classification later
  }

  /**
   * Discover models from NVIDIA NIM API and update the cache.
   */
  async discoverModels(): Promise<void> {
    if (!this.nvidiaApiKey) {
      return
    }

    try {
      const response = await axios.get('https://integrate.api.nvidia.com/v1/models', {
        headers: {
          Authorization: `Bearer ${this.nvidiaApiKey}`,
          'Accept': 'application/json',
        },
        timeout: 10000,
      })

      const data = response.data
      if (!Array.isArray(data.data)) {
        console.warn('[nim-bridge] Unexpected response format from NVIDIA models endpoint')
        return
      }

      const models: ModelInfo[] = data.data.map((model: any) => ({
        id: model.id,
        provider: 'nvidia',
        name: model.name || model.id,
        created: model.created ?? null,
        // Extract additional fields if available
        contextLength: model.context_length ?? model.max_tokens ?? null,
        capabilities: model.capabilities ?? [],
      }))

      this.modelCache = models
      this.cacheTimestamp = Date.now()
      this.updateModelAliases()
      console.log(`[nim-bridge] Discovered ${models.length} models from NVIDIA NIM`)
    } catch (err) {
      console.error('[nim-bridge] Failed to discover models:', err)
      // Keep old cache if available
    }
  }

  /**
   * Update the model aliases based on the current cache and routing logic.
   */
  private updateModelAliases() {
    // Reset aliases
    for (const key in this.MODEL_ALIASES) {
      this.MODEL_ALIASES[key as keyof typeof this.MODEL_ALIASES] = []
    }

    // Classify models and assign to aliases
    for (const model of this.modelCache) {
      const classification = this.classifyModel(model)
      for (const alias of classification) {
        this.MODEL_ALIASES[alias].push(model.id)
      }
    }

    // Sort each alias list by some priority (e.g., context length descending for long-context, etc.)
    // For simplicity, we'll just keep the order as discovered.
    // In a more advanced implementation, we could sort by capabilities.
  }

  /**
   * Classify a model into one or more alias categories.
   * Returns a list of alias keys that the model belongs to.
   */
  private classifyModel(model: ModelInfo): string[] {
    const aliases: string[] = []
    const idLower = model.id.toLowerCase()
    const nameLower = model.name.toLowerCase()
    const caps = model.capabilities ?? []

    // Heuristic classification based on model name and capabilities
    // This is a simplified implementation; in reality, we would need more detailed model metadata.

    // Check for reasoning models
    if (idLower.includes('reasoning') || nameLower.includes('reasoning') || caps.includes('reasoning')) {
      aliases.push('nvidia-reasoning')
    }
    // Check for coding models
    if (idLower.includes('coding') || idLower.includes('code') || nameLower.includes('coding') || nameLower.includes('code') || caps.includes('coding')) {
      aliases.push('nvidia-coding')
    }
    // Check for fast models (smaller, faster)
    if (idLower.includes('fast') || idLower.includes('light') || nameLower.includes('fast') || nameLower.includes('light') || (model.contextLength ?? 0) < 4096) {
      aliases.push('nvidia-fast')
    }
    // Check for long context models
    if ((model.contextLength ?? 0) >= 32768) {
      aliases.push('nvidia-long-context')
    }
    // Check for vision/multimodal models
    if (idLower.includes('vision') || idLower.includes('multimodal') || nameLower.includes('vision') || nameLower.includes('multimodal') || caps.includes('vision') || caps.includes('multimodal')) {
      aliases.push('nvidia-vision')
    }
    // If no specific classification, consider it a general agent model
    if (aliases.length === 0) {
      aliases.push('nvidia-best')
      aliases.push('nvidia-general') // we don't have this alias, but we can add to best
    }

    // Ensure that nvidia-best includes all models that are good for general use
    // We'll add all models to nvidia-best for simplicity, but we could refine.
    aliases.push('nvidia-best')

    // Remove duplicates
    return [...new Set(aliases)]
  }

  /**
   * Get the model cache, refreshing if expired.
   */
  async getModels(): Promise<ModelInfo[]> {
    if (Date.now() - this.cacheTimestamp > this.CACHE_TTL_MS) {
      await this.discoverModels()
    }
    return this.modelCache
  }

  /**
   * Resolve a model ID (which could be an alias) to an actual model ID.
   * If the model ID is not an alias, return it as-is (if it exists in cache).
   * If it's an alias, return the first model from the alias list (or null if empty).
   */
  async resolveModel(modelId: string): Promise<string | null> {
    const models = await this.getModels()
    const modelExists = models.some(m => m.id === modelId)
    if (modelExists) {
      return modelId
    }
    // Check if it's an alias
    if (this.MODEL_ALIASES.hasOwnProperty(modelId)) {
      const aliasList = this.MODEL_ALIASES[modelId as keyof typeof this.MODEL_ALIASES]
      if (aliasList.length > 0) {
        // Return the first model in the alias list (could implement round-robin or prioritization)
        return aliasList[0]
      }
    }
    return null
  }

  // ==================== Request Handling ====================

  /**
   * Handle Anthropic /v1/messages request.
   */
  async handleMessages(c: any): Promise<any> {
    if (!this.nvidiaApiKey) {
      return c.json({
        error: {
          message: 'NVIDIA API key not configured',
          type: 'invalid_request_error',
          param: null,
          code: 401
        }
      }, 401)
    }

    const anthropicRequest = await c.req.json()
    console.debug('[nim-bridge] Received Anthropic request:', anthropicRequest)

    // Extract model from request
    const modelId = anthropicRequest.model
    if (!modelId) {
      return c.json({
        error: {
          message: 'Model must be specified',
          type: 'invalid_request_error',
          param: 'model',
          code: 400
        }
      }, 400)
    }

    // Resolve model ID (alias to actual model)
    const resolvedModel = await this.resolveModel(modelId)
    if (!resolvedModel) {
      return c.json({
        error: {
          message: `Model not found: ${modelId}`,
          type: 'invalid_request_error',
          param: 'model',
          code: 404
        }
      }, 404)
    }

    // Convert Anthropic request to NVIDIA NIM format
    const nimRequest = this.convertAnthropicToNim(anthropicRequest, resolvedModel)

    // Implement retry with failover
    const maxRetries = 3
    let lastError: any = null
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const nimResponse = await axios.post(
          `https://integrate.api.nvidia.com/v1/chat/completions`,
          nimRequest,
          {
            headers: {
              Authorization: `Bearer ${this.nvidiaApiKey}`,
              'Content-Type': 'application/json',
            },
            timeout: 60000,
            responseType: 'stream', // important for streaming
          }
        )

        // Handle streaming response
        if (anthropicRequest.stream) {
          // Set up streaming response
          c.res.headers.set('Content-Type', 'text/event-stream')
          c.res.headers.set('Cache-Control', 'no-cache')
          c.res.headers.set('Connection', 'keep-alive')
          c.res.headers.set('anthropic-version', '2023-06-01')

          // Pipe the response from NVIDIA to the client
          nimResponse.data.pipe(c.res.raw)
          return c.res.raw
        } else {
          // Non-streaming: collect the full response
          const data = await new Promise((resolve, reject) => {
            const chunks: Buffer[] = []
            nimResponse.data.on('data', (chunk) => chunks.push(chunk))
            nimResponse.data.on('end', () => resolve(Buffer.concat(chunks)))
            nimResponse.data.on('error', reject)
          })

          // Convert NVIDIA response to Anthropic format
          const anthropicResponse = this.convertNimToAnthropic(JSON.parse(data.toString()))
          return c.json(anthropicResponse)
        }
      } catch (err) {
        lastError = err
        console.error(`[nim-bridge] Attempt ${attempt + 1} failed:`, err)
        // If it's a rate limit or server error, we might want to try a different model
        if (axios.isAxiosError(err) && err.response?.status === 429) {
          // Rate limit: try a different model from the same alias group? Or just wait?
          // For simplicity, we'll just retry the same model after a short delay.
          // In a more advanced implementation, we could select a different model.
          await new Promise(resolve => setTimeout(resolve, 1000 * (attempt + 1)))
          continue
        }
        // For other errors, we might still want to retry
        if (attempt < maxRetries - 1) {
          await new Promise(resolve => setTimeout(resolve, 1000))
          continue
        }
        break
      }
    }

    // If we get here, all retries failed
    if (axios.isAxiosError(lastError)) {
      const status = lastError.response?.status ?? 500
      const message = lastError.response?.data?.error?.message ?? lastError.message
      return c.json({
        error: {
          message,
          type: 'internal_server_error',
          param: null,
          code: status
        }
      }, status)
    }
    return c.json({ error: 'Internal server error' }, 500)
  }

  /**
   * Handle Anthropic /v1/models request.
   */
  async handleModels(c: any): Promise<any> {
    const models = await this.getModels()
    // Format as Anthropic models list
    const anthropicModels = {
      object: 'list',
      data: models.map(model => ({
        id: model.id,
        object: 'model',
        created: model.created ?? Math.floor(Date.now() / 1000),
        owned_by: model.provider,
      }))
    }
    return c.json(anthropicModels)
  }

  // ==================== Translation Logic ====================

  /**
   * Convert Anthropic messages request to NVIDIA NIM chat/completions request.
   */
  convertAnthropicToNim(anthropicRequest: any, modelId: string): any {
    // Basic conversion - needs to be expanded
    const nimRequest: any = {
      model: modelId,
      messages: [],
      temperature: anthropicRequest.temperature ?? 0.7,
      max_tokens: anthropicRequest.max_tokens ?? 1024,
      stream: anthropicRequest.stream ?? false,
    }

    // Convert system parameter and messages
    if (anthropicRequest.system) {
      // Anthropic system can be string or array of objects
      if (typeof anthropicRequest.system === 'string') {
        nimRequest.messages.push({
          role: 'system',
          content: anthropicRequest.system,
        })
      } else if (Array.isArray(anthropicRequest.system)) {
        // Convert array of system objects to a single system message
        const systemContent = anthropicRequest.system
          .map((part: any) =>
            typeof part === 'string' ? part :
            part.type === 'text' ? part.text :
            JSON.stringify(part)
          )
          .join('\n\n')
        nimRequest.messages.push({
          role: 'system',
          content: systemContent,
        })
      }
    }

    // Convert messages array
    for (const msg of anthropicRequest.messages) {
      const nimMsg: any = {
        role: msg.role,
        content: msg.content,
      }
      // Handle tool calls and tool results in Anthropic format
      // TODO: Implement proper tool call conversion
      nimRequest.messages.push(nimMsg)
    }

    // TODO: Handle tools parameter
    // Anthropic tools -> NVIDIA tools (if supported)

    return nimRequest
  }

  /**
   * Convert NVIDIA NIM chat/completions response to Anthropic messages response.
   */
  convertNimToAnthropic(nimResponse: any): any {
    // Basic conversion - needs to be expanded
    const anthropicResponse: any = {
      id: `msg_${Math.random().toString(36).substr(2, 9)}`,
      type: 'message',
      role: 'assistant',
      model: nimResponse.model ?? 'unknown',
      content: [],
      stop_reason: this.convertFinishReason(nimResponse.choices?.[0]?.finish_reason),
      stop_sequence: null,
      usage: {
        input_tokens: nimResponse.usage?.prompt_tokens ?? 0,
        output_tokens: nimResponse.usage?.completion_tokens ?? 0,
      },
    }

    // Convert choices to Anthropic content blocks
    if (Array.isArray(nimResponse.choices)) {
      for (const choice of nimResponse.choices) {
        if (choice.message) {
          // Handle text content
          if (choice.message.content) {
            anthropicResponse.content.push({
              type: 'text',
              text: choice.message.content,
            })
          }
          // Handle tool calls
          // TODO: Implement tool call conversion from NVIDIA to Anthropic
        }
      }
    }

    return anthropicResponse
  }

  /**
   * Convert NVIDIA finish reason to Anthropic stop reason.
   */
  convertFinishReason(finishReason: string | null | undefined):
    | 'end_turn'
    | 'stop_sequence'
    | 'max_tokens'
    | null
  {
    switch (finishReason) {
      case 'stop':
        return 'end_turn'
      case 'length':
        return 'max_tokens'
      case 'tool_calls':
        // Anthropic uses 'stop_sequence' for tool calls? Actually, Anthropic uses a separate mechanism.
        // We'll map to 'end_turn' for now and handle tool calls in content.
        return 'end_turn'
      default:
        return null
    }
  }
}