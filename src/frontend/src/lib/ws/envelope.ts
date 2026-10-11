/**
 * Конверт текстового сообщения WebSocket (ADR-004, 3.3; SYS-04-R3) и
 * заголовок бинарного кадра (SYS-04-R9). После появления
 * Analytics/Specs/_system/asyncapi-common.yaml (этап 1 Г.3) схема
 * сверяется со сгенерированной в src/lib/ws/generated/messages.ts.
 */
import { z } from 'zod';

/** Ровно шесть полей; лишние или отсутствующие — сообщение отклоняется. */
export const WsEnvelopeSchema = z
  .object({
    type: z.string().regex(/^[a-z0-9_]+(\.[a-z0-9_]+)+$/),
    correlation_id: z.string().min(1),
    channel: z.string().nullable(),
    seq: z.number().int().nonnegative(),
    ts: z.string(),
    payload: z.record(z.string(), z.unknown()),
  })
  .strict();

export type WsEnvelope<P = Record<string, unknown>> = Omit<
  z.infer<typeof WsEnvelopeSchema>,
  'payload'
> & { payload: P };

/** Максимальный размер сообщения (WS_MAX_MESSAGE_BYTES, SYS-04-R3). */
export const WS_MAX_MESSAGE_BYTES = 64 * 1024;

/** Разбирает текст в конверт; невалидное сообщение — `null`. */
export const parseEnvelope = (data: string): WsEnvelope | null => {
  try {
    const result = WsEnvelopeSchema.safeParse(JSON.parse(data));
    return result.success ? result.data : null;
  } catch {
    return null;
  }
};

/** Типы бинарных кадров (SYS-04-R9). */
export const BinaryFrameType = {
  CLIENT_AUDIO: 0x01,
  SERVER_AUDIO: 0x02,
} as const;

export const BINARY_HEADER_BYTES = 9;

export type BinaryFrame = {
  type: number;
  streamId: number;
  seq: number;
  data: Uint8Array;
};

/** Кадр: тип (1 байт), stream_id (4 байта BE), seq (4 байта BE), данные. */
export const encodeBinaryFrame = ({
  type,
  streamId,
  seq,
  data,
}: BinaryFrame): Uint8Array<ArrayBuffer> => {
  const frame = new Uint8Array(BINARY_HEADER_BYTES + data.byteLength);
  const view = new DataView(frame.buffer);
  view.setUint8(0, type);
  view.setUint32(1, streamId, false);
  view.setUint32(5, seq, false);
  frame.set(data, BINARY_HEADER_BYTES);
  return frame;
};

export const decodeBinaryFrame = (buffer: ArrayBuffer): BinaryFrame | null => {
  if (buffer.byteLength < BINARY_HEADER_BYTES) return null;
  const view = new DataView(buffer);
  return {
    type: view.getUint8(0),
    streamId: view.getUint32(1, false),
    seq: view.getUint32(5, false),
    data: new Uint8Array(buffer, BINARY_HEADER_BYTES),
  };
};
