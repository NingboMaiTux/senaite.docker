// HTTP 客户端：封装 fetch，拆解后端统一响应 {success, data, error, meta}。
// 与后端 web/response.py 的格式严格对齐。

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  suggestion?: string;
}

export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  error: ApiError | null;
  meta: { request_id: string; duration_ms: number };
}

/** 业务/网络错误统一抛成该类型，组件可读 code/suggestion */
export class ApiCallError extends Error {
  code: string;
  suggestion?: string;
  details?: Record<string, unknown>;

  constructor(err: ApiError) {
    super(err.message);
    this.name = 'ApiCallError';
    this.code = err.code;
    this.suggestion = err.suggestion;
    this.details = err.details;
  }
}

const BASE = '/api';

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  let envelope: ApiEnvelope<T>;
  try {
    envelope = (await res.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiCallError({
      code: 'NETWORK_ERROR',
      message: `响应解析失败（HTTP ${res.status}）`,
    });
  }

  if (!envelope.success || envelope.error) {
    throw new ApiCallError(
      envelope.error ?? { code: 'UNKNOWN', message: '未知错误' },
    );
  }
  return envelope.data as T;
}

export const apiClient = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
};
