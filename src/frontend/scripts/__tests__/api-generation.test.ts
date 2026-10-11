import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { featureNameOf, listOpenApiModules } from '../../orval.config';
import {
  generateMessagesModule,
  listAsyncApiTargets,
  schemaNameOf,
} from '../asyncapi-to-zod';

const ASYNCAPI = `
asyncapi: 3.0.0
info: { title: probe, version: 1.0.0 }
channels:
  stream:
    address: probe.stream
    x-flt-transport: websocket
    messages:
      delta: { $ref: '#/components/messages/delta' }
  events:
    address: flt.probe.item_created.v1
    x-flt-transport: kafka
    messages:
      created: { $ref: '#/components/messages/created' }
operations:
  receiveDelta:
    action: receive
    channel: { $ref: '#/channels/stream' }
components:
  messages:
    delta:
      name: probe.stream.delta
      payload:
        type: object
        required: [seq, text]
        properties:
          seq: { type: integer, minimum: 0 }
          text: { type: string }
    created:
      name: probe.item_created
      payload: { type: object, properties: { id: { type: string } } }
`;

const makeSpecs = (files: Record<string, string>) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'flt-specs-'));
  for (const [file, content] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    fs.writeFileSync(path.join(dir, file), content);
  }
  return dir;
};

describe('API generation from contracts', () => {
  it('[SYS-03-R23] empty contract list is a valid state', () => {
    const dir = makeSpecs({ '_templates/README.md': '' });
    expect(listOpenApiModules(dir)).toEqual([]);
    expect(listAsyncApiTargets(dir)).toEqual([]);
    expect(listOpenApiModules(path.join(dir, 'missing'))).toEqual([]);
  });

  it('[SYS-03-R23] OpenAPI contracts are discovered per module, service dirs skipped', () => {
    const dir = makeSpecs({
      'identity/api/openapi.yaml': 'openapi: 3.1.0',
      'llm_gateway/api/openapi.yaml': 'openapi: 3.1.0',
      'app_shell/_module.md': '',
      '_system/openapi-common.yaml': 'openapi: 3.1.0',
    });
    expect(listOpenApiModules(dir)).toEqual(['identity', 'llm_gateway']);
    expect(featureNameOf('llm_gateway')).toBe('llm-gateway');
  });

  it('[SYS-04-R33] AsyncAPI targets: module messages and the common envelope', () => {
    const dir = makeSpecs({
      'llm_gateway/api/asyncapi.yaml': ASYNCAPI,
      '_system/asyncapi-common.yaml': ASYNCAPI,
    });
    const outputs = listAsyncApiTargets(dir).map((t) =>
      t.output.split(path.sep).slice(-5).join('/'),
    );
    expect(outputs).toEqual([
      'features/llm-gateway/ws/generated/messages.ts',
      'src/lib/ws/generated/messages.ts',
    ]);
  });

  it('[SYS-04-R33] generates zod schemas only for WebSocket messages', async () => {
    const code = await generateMessagesModule(ASYNCAPI);
    expect(code).toContain('export const ProbeStreamDeltaSchema = z.object(');
    expect(code).toContain(
      'export type ProbeStreamDelta = z.infer<typeof ProbeStreamDeltaSchema>;',
    );
    expect(code).not.toContain('ProbeItemCreated');
    expect(schemaNameOf('llm_gateway.stream.delta')).toBe(
      'LlmGatewayStreamDelta',
    );
  }, 30_000);
});
