import { backoffDelay, decideReconnect } from './backoff';
import {
  BINARY_HEADER_BYTES,
  BinaryFrameType,
  decodeBinaryFrame,
  encodeBinaryFrame,
  parseEnvelope,
} from './envelope';

const valid = {
  type: 'llm_gateway.stream.delta',
  correlation_id: '0192f3a0-0000-7000-8000-000000000001',
  channel: 'llm_gateway.stream:1',
  seq: 3,
  ts: '2026-10-10T12:00:00.000Z',
  payload: { text: 'hi' },
};

describe('envelope', () => {
  it('[SYS-04-R3] accepts exactly the six envelope fields', () => {
    expect(parseEnvelope(JSON.stringify(valid))).toEqual(valid);
    expect(parseEnvelope(JSON.stringify({ ...valid, extra: 1 }))).toBeNull();
    const withoutSeq: Partial<typeof valid> = { ...valid };
    delete withoutSeq.seq;
    expect(parseEnvelope(JSON.stringify(withoutSeq))).toBeNull();
    expect(
      parseEnvelope(JSON.stringify({ ...valid, type: 'Bad Type' })),
    ).toBeNull();
    expect(parseEnvelope('not json')).toBeNull();
  });

  it('[SYS-04-R9] binary frames have a 9-byte big-endian header', () => {
    const data = new Uint8Array([1, 2, 3]);
    const frame = encodeBinaryFrame({
      type: BinaryFrameType.CLIENT_AUDIO,
      streamId: 0x01020304,
      seq: 7,
      data,
    });
    expect(frame.byteLength).toBe(BINARY_HEADER_BYTES + 3);
    expect([...frame.slice(0, 9)]).toEqual([1, 1, 2, 3, 4, 0, 0, 0, 7]);

    const decoded = decodeBinaryFrame(frame.buffer as ArrayBuffer);
    expect(decoded).toMatchObject({ type: 1, streamId: 0x01020304, seq: 7 });
    expect([...(decoded?.data ?? [])]).toEqual([1, 2, 3]);
    expect(decodeBinaryFrame(new ArrayBuffer(4))).toBeNull();
  });
});

describe('backoff', () => {
  it('[SYS-04-R12] exponential delay from 1 to 30 s with full jitter', () => {
    expect(backoffDelay(0, () => 0.99)).toBe(1000);
    expect(backoffDelay(3, () => 0)).toBe(1000);
    expect(backoffDelay(3, () => 1)).toBe(8000);
    expect(backoffDelay(10, () => 1)).toBe(30000);
  });

  it('[SYS-04-R10] decisions per close code', () => {
    const random = () => 0;
    expect(decideReconnect(1000, 0, random)).toEqual({ kind: 'none' });
    expect(decideReconnect(1012, 5, random)).toEqual({ kind: 'delay', ms: 0 });
    expect(decideReconnect(4401, 0, random)).toEqual({ kind: 'refresh' });
    expect(decideReconnect(4429, 0, random)).toEqual({
      kind: 'too-many-connections',
      ms: 10000,
    });
    expect(decideReconnect(1008, 0, random)).toEqual({
      kind: 'delay',
      ms: 30000,
    });
    expect(decideReconnect(1006, 2, () => 1)).toEqual({
      kind: 'delay',
      ms: 4000,
    });
  });
});
